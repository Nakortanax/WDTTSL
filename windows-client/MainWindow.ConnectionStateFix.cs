using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;

namespace VPNSL.Windows;

public partial class MainWindow
{
    private static readonly string[] WindowsControlHosts =
    [
        "api.vk.me",
        "calls.okcdn.ru",
        "login.vk.ru",
        "api.vk.ru",
    ];

    private readonly object _transportGuardGate = new();
    private readonly HashSet<string> _transportGuardHosts = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _transportGuardPrefixes = new(StringComparer.OrdinalIgnoreCase);
    private bool _connectionStateFixAttached;
    private uint _transportGuardInterface;
    private string? _transportGuardNextHop;

    protected override void OnContentRendered(EventArgs e)
    {
        base.OnContentRendered(e);
        if (_connectionStateFixAttached) return;
        _connectionStateFixAttached = true;

        // Keep the cancel/disconnect button usable while ConnectAsync is still
        // running and pre-protect client.exe control sockets from full-tunnel.
        _engine.StatusChanged += OnConnectionStateForButton;
        _engine.Log += OnEngineLogForTransportGuard;
    }

    private void OnConnectionStateForButton(string status)
    {
        if (status.Equals("Подключение", StringComparison.Ordinal))
            PrepareWindowsTransportGuard();
        else if (status.Equals("Отключено", StringComparison.Ordinal))
            CleanupWindowsTransportGuard();

        Dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() =>
        {
            if (status.Equals("Подключение", StringComparison.Ordinal))
            {
                ConnectButton.Content = "Отменить подключение";
                ConnectButton.IsEnabled = true;
            }
            else if (status.Equals("Подключено", StringComparison.Ordinal))
            {
                ConnectButton.Content = "Отключить";
                ConnectButton.IsEnabled = true;
            }
            else if (status.Equals("Отключено", StringComparison.Ordinal))
            {
                ConnectButton.Content = "Подключить";
                ConnectButton.IsEnabled = true;
            }
        }));
    }

    private void PrepareWindowsTransportGuard()
    {
        try
        {
            CleanupWindowsTransportGuard();
            lock (_transportGuardGate) _transportGuardHosts.Clear();

            var physical = GetGuardPhysicalRoute();
            if (physical is null)
            {
                Ui(() => AppendLog("[ROUTE] Предохранитель: физический IPv4-шлюз не найден"));
                return;
            }

            _transportGuardInterface = physical.Value.InterfaceIndex;
            _transportGuardNextHop = physical.Value.NextHop;

            foreach (var host in WindowsControlHosts)
                RegisterGuardHost(host, installNow: true);

            RegisterGuardHost(ExtractGuardHost(_settings.Peer), installNow: true);
            RegisterGuardHost(ExtractGuardHost(_settings.TurnHost), installNow: true);

            Ui(() => AppendLog(
                $"[ROUTE] Предохранитель транспорта: ifIndex={_transportGuardInterface}, nextHop={_transportGuardNextHop}"));
        }
        catch (Exception ex)
        {
            Ui(() => AppendLog($"[ROUTE] Предохранитель транспорта: {ex.Message}"));
        }
    }

    private void OnEngineLogForTransportGuard(string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;

        try
        {
            CaptureTurnHosts(line);

            // VpnEngine writes this line synchronously immediately after CONFIG
            // and before Wintun/full-tunnel. Give stderr a short time to flush
            // the TURN credential/connection lines, then install every captured
            // physical /32 route before the two /1 routes can be created.
            if (line.StartsWith("[WINDOWS] Получена конфигурация TUN:", StringComparison.Ordinal))
            {
                Thread.Sleep(700);
                FlushGuardHostsSynchronously();
                Ui(() => AppendLog("[ROUTE] Предохранитель: контрольные и TURN-маршруты закреплены до full-tunnel"));
            }
        }
        catch (Exception ex)
        {
            Ui(() => AppendLog($"[ROUTE] Предохранитель: {ex.Message}"));
        }
    }

    private void CaptureTurnHosts(string line)
    {
        const string connectMarker = "[TURN] Подключение к ";
        var marker = line.IndexOf(connectMarker, StringComparison.Ordinal);
        if (marker >= 0)
        {
            RegisterGuardHost(ExtractGuardHost(line[(marker + connectMarker.Length)..]), installNow: _engine.IsRunning);
        }

        const string credentialMarker = "OK, TURN: ";
        marker = line.IndexOf(credentialMarker, StringComparison.Ordinal);
        if (marker < 0 || !line.Contains("[КРЕД #", StringComparison.Ordinal)) return;

        var start = line.IndexOf('[', marker + credentialMarker.Length);
        var end = line.LastIndexOf(']');
        if (start < 0 || end <= start) return;

        try
        {
            using var document = JsonDocument.Parse(line[start..(end + 1)]);
            if (document.RootElement.ValueKind != JsonValueKind.Array) return;
            foreach (var element in document.RootElement.EnumerateArray())
            {
                if (element.ValueKind == JsonValueKind.String)
                    RegisterGuardHost(ExtractGuardHost(element.GetString() ?? ""), installNow: _engine.IsRunning);
            }
        }
        catch (JsonException)
        {
        }
    }

    private void RegisterGuardHost(string host, bool installNow)
    {
        if (string.IsNullOrWhiteSpace(host)) return;
        var normalized = host.Trim();
        var added = false;
        lock (_transportGuardGate) added = _transportGuardHosts.Add(normalized);
        if ((added && installNow) || (installNow && _engine.IsRunning))
            EnsureGuardHostRoutes(normalized);
    }

    private void FlushGuardHostsSynchronously()
    {
        string[] hosts;
        lock (_transportGuardGate) hosts = _transportGuardHosts.ToArray();
        foreach (var host in hosts) EnsureGuardHostRoutes(host);
    }

    private void EnsureGuardHostRoutes(string host)
    {
        var nextHop = _transportGuardNextHop;
        var interfaceIndex = _transportGuardInterface;
        if (interfaceIndex == 0 || string.IsNullOrWhiteSpace(nextHop) || string.IsNullOrWhiteSpace(host)) return;

        IPAddress[] addresses;
        try
        {
            if (IPAddress.TryParse(host, out var literal))
                addresses = literal.AddressFamily == AddressFamily.InterNetwork ? [literal] : [];
            else
                addresses = Dns.GetHostAddresses(host)
                    .Where(x => x.AddressFamily == AddressFamily.InterNetwork)
                    .Distinct()
                    .ToArray();
        }
        catch
        {
            return;
        }

        foreach (var address in addresses)
        {
            var prefix = $"{address}/32";
            var alreadyTracked = false;
            lock (_transportGuardGate) alreadyTracked = _transportGuardPrefixes.Contains(prefix);
            if (alreadyTracked) continue;

            var command =
                $"$e=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '{prefix}' -InterfaceIndex {interfaceIndex} -ErrorAction SilentlyContinue | Where-Object {{ $_.NextHop -eq '{nextHop}' }}); " +
                $"if ($e.Count -eq 0) {{ New-NetRoute -DestinationPrefix '{prefix}' -InterfaceIndex {interfaceIndex} -NextHop '{nextHop}' -RouteMetric 0 -PolicyStore ActiveStore -ErrorAction Stop | Out-Null; Write-Output 'ADDED' }} else {{ Write-Output 'EXISTS' }}";
            RunGuardPowerShell(command);
            lock (_transportGuardGate) _transportGuardPrefixes.Add(prefix);
        }
    }

    private void CleanupWindowsTransportGuard()
    {
        string[] prefixes;
        uint interfaceIndex;
        string? nextHop;
        lock (_transportGuardGate)
        {
            prefixes = _transportGuardPrefixes.ToArray();
            _transportGuardPrefixes.Clear();
            interfaceIndex = _transportGuardInterface;
            nextHop = _transportGuardNextHop;
            _transportGuardInterface = 0;
            _transportGuardNextHop = null;
        }

        if (prefixes.Length == 0 || interfaceIndex == 0 || string.IsNullOrWhiteSpace(nextHop)) return;
        try
        {
            foreach (var prefix in prefixes)
            {
                var command =
                    $"Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '{prefix}' -InterfaceIndex {interfaceIndex} -ErrorAction SilentlyContinue | " +
                    $"Where-Object {{ $_.NextHop -eq '{nextHop}' }} | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue";
                RunGuardPowerShell(command);
            }
        }
        catch
        {
        }
    }

    private static (uint InterfaceIndex, string NextHop)? GetGuardPhysicalRoute()
    {
        var command =
            "$items = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | " +
            "Where-Object { $_.NextHop -ne '0.0.0.0' } | ForEach-Object { " +
            "$if = Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue; " +
            "$cost = [int]$_.RouteMetric + [int]($if.InterfaceMetric); [PSCustomObject]@{ Route=$_; Cost=$cost } }; " +
            "$x=$items | Sort-Object Cost | Select-Object -First 1; if ($x) { Write-Output ($x.Route.InterfaceIndex.ToString() + '|' + $x.Route.NextHop) }";
        var output = RunGuardPowerShell(command).Trim();
        var parts = output.Split('|', 2);
        return parts.Length == 2 && uint.TryParse(parts[0], out var index) && parts[1].Length > 0
            ? (index, parts[1])
            : null;
    }

    private static string RunGuardPowerShell(string command)
    {
        var info = new ProcessStartInfo("powershell.exe")
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        info.ArgumentList.Add("-NoProfile");
        info.ArgumentList.Add("-NonInteractive");
        info.ArgumentList.Add("-ExecutionPolicy");
        info.ArgumentList.Add("Bypass");
        info.ArgumentList.Add("-Command");
        info.ArgumentList.Add(command);

        using var process = Process.Start(info) ?? throw new InvalidOperationException("Не удалось запустить PowerShell");
        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit();
        if (process.ExitCode != 0)
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(stderr) ? $"PowerShell exit {process.ExitCode}" : stderr.Trim());
        return stdout;
    }

    private static string ExtractGuardHost(string? endpoint)
    {
        var text = endpoint?.Trim().Trim('"', '\'') ?? "";
        if (text.Length == 0) return "";
        if (text.StartsWith("turns:", StringComparison.OrdinalIgnoreCase)) text = text[6..];
        else if (text.StartsWith("turn:", StringComparison.OrdinalIgnoreCase)) text = text[5..];
        if (text.StartsWith("//", StringComparison.Ordinal)) text = text[2..];
        var query = text.IndexOf('?');
        if (query >= 0) text = text[..query];

        if (text.StartsWith("[", StringComparison.Ordinal))
        {
            var close = text.IndexOf(']');
            return close > 1 ? text[1..close] : "";
        }
        if (IPAddress.TryParse(text, out _)) return text;
        if (text.Count(ch => ch == ':') == 1)
        {
            var colon = text.LastIndexOf(':');
            if (colon > 0) return text[..colon];
        }
        return text;
    }
}
