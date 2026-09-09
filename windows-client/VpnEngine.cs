using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;

namespace VPNSL.Windows;

internal sealed class VpnEngine : IDisposable
{
    private readonly object _gate = new();
    private readonly object _stdinGate = new();
    private CancellationTokenSource? _cancellation;
    private Process? _client;
    private WintunAdapter? _wintun;
    private readonly List<(string Prefix, uint InterfaceIndex)> _installedRoutes = [];
    private TaskCompletionSource<(string Ip, string Dns)>? _configSource;
    private bool _running;

    public bool IsRunning => _running;
    public bool IsActive => _running || _cancellation is not null;
    public event Action<string>? Log;
    public event Action<string>? StatusChanged;
    public event Action<int, long, long>? StatsChanged;

    public async Task ConnectAsync(AppSettings settings)
    {
        CancellationTokenSource sessionCancellation;
        lock (_gate)
        {
            if (_running || _cancellation is not null) return;
            sessionCancellation = new CancellationTokenSource();
            _cancellation = sessionCancellation;
            _configSource = new(TaskCreationOptions.RunContinuationsAsynchronously);
        }

        var token = sessionCancellation.Token;
        try
        {
            Validate(settings);
            StatusChanged?.Invoke("Подключение");
            Log?.Invoke("[WINDOWS] Запуск VPNSL 1.0.8");

            var physical = await GetPhysicalDefaultRouteAsync(0, token);
            var port = FindFreeUdpPort();
            StartClient(settings, port, token);

            var config = await _configSource!.Task.WaitAsync(token);
            Log?.Invoke($"[WINDOWS] Получена конфигурация TUN: {config.Ip}/32, DNS {config.Dns}");

            _wintun = new WintunAdapter();
            _wintun.Open();
            await ConfigureAdapterAsync(_wintun.InterfaceIndex, config.Ip, config.Dns, token);

            physical = await GetPhysicalDefaultRouteAsync(_wintun.InterfaceIndex, token) ?? physical;
            await ApplyRoutePolicyAsync(settings, _wintun.InterfaceIndex, physical, token);
            await ProtectPeerAsync(settings.Peer, physical, token);

            _wintun.StartBridge(port, message => Log?.Invoke(message), token);
            _running = true;
            StatusChanged?.Invoke("Подключено");
            Log?.Invoke($"[WINDOWS] Wintun активен, interface index {_wintun.InterfaceIndex}");
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            await DisconnectAsync();
        }
        catch
        {
            await DisconnectAsync();
            throw;
        }
    }

    public async Task DisconnectAsync()
    {
        CancellationTokenSource? cancellation;
        lock (_gate)
        {
            cancellation = _cancellation;
            if (cancellation is null && !_running) return;
            _cancellation = null;
            _running = false;
        }

        StatusChanged?.Invoke("Отключение…");
        try { cancellation?.Cancel(); } catch { }

        try { _wintun?.Dispose(); } catch (Exception ex) { Log?.Invoke($"[WINDOWS] Wintun stop: {ex.Message}"); }
        _wintun = null;

        await RemoveInstalledRoutesAsync();

        var client = _client;
        _client = null;
        if (client is not null)
        {
            try
            {
                if (!client.HasExited)
                {
                    TrySendControlCommand(client, "STOP");
                    if (!client.WaitForExit(1200)) client.Kill(true);
                }
            }
            catch
            {
                try { client.Kill(true); } catch { }
            }
            client.Dispose();
        }

        cancellation?.Dispose();
        _configSource?.TrySetCanceled();
        _configSource = null;
        StatusChanged?.Invoke("Отключено");
        Log?.Invoke("[WINDOWS] VPN остановлен");
    }

    private void StartClient(AppSettings settings, int port, CancellationToken token)
    {
        var clientPath = Path.Combine(AppContext.BaseDirectory, "client.exe");
        if (!File.Exists(clientPath)) throw new FileNotFoundException("Рядом с VPNSL.Windows.exe отсутствует client.exe", clientPath);
        var wintunPath = Path.Combine(AppContext.BaseDirectory, "wintun.dll");
        if (!File.Exists(wintunPath)) throw new FileNotFoundException("Рядом с VPNSL.Windows.exe отсутствует wintun.dll", wintunPath);

        var info = new ProcessStartInfo(clientPath)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            CreateNoWindow = true,
            WorkingDirectory = AppContext.BaseDirectory,
        };
        info.Environment["CSQTT_EVENTS"] = "1";
        info.Environment["CSQTT_PARENT_PID"] = Environment.ProcessId.ToString(CultureInfo.InvariantCulture);

        AddArg(info, "--listen", $"127.0.0.1:{port}");
        AddArg(info, "--peer", settings.Peer.Trim());
        AddArg(info, "--vk", settings.VkHashes.Trim());
        AddArg(info, "--vk-hash-mode", string.IsNullOrWhiteSpace(settings.VkHashMode) ? "manual" : settings.VkHashMode);
        AddArg(info, "--workers", NormalizeWorkers(settings.Workers).ToString(CultureInfo.InvariantCulture));
        AddArg(info, "--device-id", settings.DeviceId);
        AddArg(info, "--password", settings.Password);
        AddArg(info, "--vk-auth-mode", settings.VkAuthMode);
        AddArg(info, "--captcha-mode", settings.CaptchaMode);
        AddArg(info, "--fingerprint", settings.Fingerprint);
        AddArg(info, "--client-ids", settings.ClientIds);
        AddArg(info, "--obfs", settings.Obfs);
        AddArg(info, "--turn-transport", settings.TurnTransport);
        AddArg(info, "--gen", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString(CultureInfo.InvariantCulture));
        AddArg(info, "--salt", Guid.NewGuid().ToString("N"));
        if (!string.IsNullOrWhiteSpace(settings.TurnHost)) AddArg(info, "--turn", settings.TurnHost.Trim());
        if (!string.IsNullOrWhiteSpace(settings.TurnPort)) AddArg(info, "--port", settings.TurnPort.Trim());

        var process = new Process { StartInfo = info, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) => HandleClientLine(e.Data);
        process.ErrorDataReceived += (_, e) => HandleClientLine(e.Data);
        process.Exited += (_, _) =>
        {
            if (!token.IsCancellationRequested)
            {
                Log?.Invoke($"[КЛИЕНТ] Процесс завершён, код {SafeExitCode(process)}");
                _ = Task.Run(async () =>
                {
                    try { await DisconnectAsync(); }
                    catch (Exception ex) { Log?.Invoke($"[WINDOWS] Очистка после остановки клиента: {ex.Message}"); }
                });
            }
        };
        if (!process.Start()) throw new InvalidOperationException("Не удалось запустить client.exe");
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        _client = process;
    }

    private bool TrySendControlCommand(Process client, string command)
    {
        try
        {
            lock (_stdinGate)
            {
                if (client.HasExited) return false;
                client.StandardInput.WriteLine(command);
                client.StandardInput.Flush();
            }
            return true;
        }
        catch (Exception ex)
        {
            Log?.Invoke($"[STDIN] {command}: {ex.Message}");
            return false;
        }
    }

    private void HandleClientLine(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        const string prefix = "__CSQTT_EVENT__|";
        if (!line.StartsWith(prefix, StringComparison.Ordinal))
        {
            Log?.Invoke(line);
            return;
        }

        try
        {
            var rest = line[prefix.Length..];
            var separator = rest.IndexOf('|');
            if (separator <= 0) return;
            var kind = rest[..separator];
            using var document = JsonDocument.Parse(rest[(separator + 1)..]);
            var root = document.RootElement;
            switch (kind)
            {
                case "CONFIG":
                    if (root.TryGetProperty("config", out var configElement))
                    {
                        var config = configElement.GetString().OrEmpty();
                        if (TryParseTunConfig(config, out var ip, out var dns))
                            _configSource?.TrySetResult((ip, dns));
                        else if (config.Equals("NOCONF", StringComparison.OrdinalIgnoreCase))
                            _configSource?.TrySetException(new InvalidOperationException("Сервер не вернул TUNCONF"));
                    }
                    break;
                case "READY":
                    if (root.TryGetProperty("worker", out var worker)) Log?.Invoke($"[КЛИЕНТ] Воркер #{worker.GetInt32()} готов");
                    break;
                case "STATS":
                    StatsChanged?.Invoke(
                        root.TryGetProperty("active", out var active) ? active.GetInt32() : 0,
                        root.TryGetProperty("bytes_up", out var up) ? up.GetInt64() : 0,
                        root.TryGetProperty("bytes_down", out var down) ? down.GetInt64() : 0);
                    break;
                case "ERROR":
                    var message = root.TryGetProperty("message", out var errorMessage) ? errorMessage.GetString().OrEmpty() : "Ошибка VPN";
                    Log?.Invoke($"[ОШИБКА] {message}");
                    if (root.TryGetProperty("fatal", out var fatal) && fatal.GetBoolean())
                        _configSource?.TrySetException(new InvalidOperationException(message));
                    break;
                case "NETWORK_SUSPECT":
                    Log?.Invoke("[NET] Сеть нестабильна, клиент восстанавливает соединение");
                    break;
                case "SERVER_RESTART":
                    Log?.Invoke("[СЕРВЕР] Обнаружен перезапуск панели");
                    break;
            }
        }
        catch (Exception ex)
        {
            Log?.Invoke($"[EVENT] {ex.Message}");
        }
    }

    private async Task ApplyRoutePolicyAsync(
        AppSettings settings,
        uint tunnelInterface,
        DefaultRoute? physical,
        CancellationToken token)
    {
        var chosen = new Dictionary<string, RouteTarget>(StringComparer.OrdinalIgnoreCase);
        foreach (var profile in settings.Routes.Where(p => p.Enabled))
        {
            foreach (var raw in profile.Routes)
            {
                if (RoutePolicy.TryNormalize(raw, out var cidr) && !chosen.ContainsKey(cidr))
                    chosen[cidr] = profile.Target;
            }
        }

        foreach (var route in chosen.OrderByDescending(r => PrefixLength(r.Key)))
        {
            if (route.Value == RouteTarget.VPNSL)
            {
                await AddRouteAsync(route.Key, tunnelInterface, "0.0.0.0", 5, token);
            }
            else if (physical is not null)
            {
                await AddRouteAsync(route.Key, physical.InterfaceIndex, physical.NextHop, 1, token);
            }
        }
        Log?.Invoke($"[ROUTE] Активно правил: {chosen.Count}; через VPNSL: {chosen.Count(x => x.Value == RouteTarget.VPNSL)}");
    }

    private async Task ProtectPeerAsync(string peer, DefaultRoute? physical, CancellationToken token)
    {
        if (physical is null) return;
        var host = ExtractHost(peer);
        if (host.Length == 0) return;
        try
        {
            var addresses = await Dns.GetHostAddressesAsync(host, token);
            foreach (var ip in addresses.Where(x => x.AddressFamily == AddressFamily.InterNetwork))
                await AddRouteAsync($"{ip}/32", physical.InterfaceIndex, physical.NextHop, 0, token);
        }
        catch (Exception ex)
        {
            Log?.Invoke($"[ROUTE] Не удалось защитить адрес peer от зацикливания: {ex.Message}");
        }
    }

    private async Task ConfigureAdapterAsync(uint index, string ip, string dns, CancellationToken token)
    {
        var command =
            $"Get-NetIPAddress -InterfaceIndex {index} -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue; " +
            $"New-NetIPAddress -InterfaceIndex {index} -IPAddress '{Ps(ip)}' -PrefixLength 32 -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop | Out-Null; " +
            $"Set-DnsClientServerAddress -InterfaceIndex {index} -ServerAddresses @('{Ps(dns)}') -ErrorAction Stop; " +
            $"Set-NetIPInterface -InterfaceIndex {index} -AddressFamily IPv4 -InterfaceMetric 5 -ErrorAction SilentlyContinue";
        await PowerShellAsync(command, token);
    }

    private async Task AddRouteAsync(string prefix, uint index, string nextHop, int metric, CancellationToken token)
    {
        var command =
            $"Remove-NetRoute -DestinationPrefix '{Ps(prefix)}' -InterfaceIndex {index} -Confirm:$false -ErrorAction SilentlyContinue; " +
            $"New-NetRoute -DestinationPrefix '{Ps(prefix)}' -InterfaceIndex {index} -NextHop '{Ps(nextHop)}' -RouteMetric {metric} -PolicyStore ActiveStore -ErrorAction Stop | Out-Null";
        await PowerShellAsync(command, token);
        _installedRoutes.Add((prefix, index));
    }

    private async Task RemoveInstalledRoutesAsync()
    {
        foreach (var route in _installedRoutes.AsEnumerable().Reverse())
        {
            try
            {
                await PowerShellAsync(
                    $"Remove-NetRoute -DestinationPrefix '{Ps(route.Prefix)}' -InterfaceIndex {route.InterfaceIndex} -Confirm:$false -ErrorAction SilentlyContinue",
                    CancellationToken.None);
            }
            catch { }
        }
        _installedRoutes.Clear();
    }

    private static async Task<DefaultRoute?> GetPhysicalDefaultRouteAsync(uint excludedInterface, CancellationToken token)
    {
        var command =
            "$r = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | " +
            $"Where-Object {{ $_.InterfaceIndex -ne {excludedInterface} -and $_.NextHop -ne '0.0.0.0' }} | " +
            "Sort-Object RouteMetric | Select-Object -First 1; if ($r) { Write-Output ($r.InterfaceIndex.ToString() + '|' + $r.NextHop) }";
        var output = (await PowerShellAsync(command, token)).Trim();
        var parts = output.Split('|', 2);
        return parts.Length == 2 && uint.TryParse(parts[0], out var index) && parts[1].Length > 0
            ? new DefaultRoute(index, parts[1])
            : null;
    }

    private static async Task<string> PowerShellAsync(string command, CancellationToken token)
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
        var stdoutTask = process.StandardOutput.ReadToEndAsync(token);
        var stderrTask = process.StandardError.ReadToEndAsync(token);
        await process.WaitForExitAsync(token);
        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        if (process.ExitCode != 0) throw new InvalidOperationException(stderr.Trim().Length > 0 ? stderr.Trim() : $"PowerShell exit {process.ExitCode}");
        return stdout;
    }

    private static bool TryParseTunConfig(string value, out string ip, out string dns)
    {
        ip = dns = "";
        if (!value.StartsWith("TUNCONF:", StringComparison.Ordinal)) return false;
        var parts = value[8..].Split(':', 3);
        if (parts.Length < 2 || !IPAddress.TryParse(parts[0], out var ipAddress) || ipAddress.AddressFamily != AddressFamily.InterNetwork || !IPAddress.TryParse(parts[1], out _))
            return false;
        ip = parts[0];
        dns = parts[1];
        return true;
    }

    private static string ExtractHost(string peer)
    {
        var text = peer.Trim();
        if (text.Length == 0) return "";
        if (Uri.TryCreate("udp://" + text, UriKind.Absolute, out var uri)) return uri.Host;
        return text.Split(':')[0];
    }

    private static int PrefixLength(string cidr) => int.TryParse(cidr[(cidr.LastIndexOf('/') + 1)..], out var prefix) ? prefix : 0;

    private static int FindFreeUdpPort()
    {
        using var probe = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
        return ((IPEndPoint)probe.Client.LocalEndPoint!).Port;
    }

    private static int NormalizeWorkers(int value) => Math.Clamp(value, 9, 126) / 9 * 9;
    private static string Ps(string value) => value.Replace("'", "''");
    private static int SafeExitCode(Process process) { try { return process.ExitCode; } catch { return -1; } }
    private static void AddArg(ProcessStartInfo info, string name, string value) { info.ArgumentList.Add(name); info.ArgumentList.Add(value); }

    private static void Validate(AppSettings settings)
    {
        if (string.IsNullOrWhiteSpace(settings.Peer)) throw new ArgumentException("Укажите Peer в настройках подключения");
        if (string.IsNullOrWhiteSpace(settings.Password)) throw new ArgumentException("Укажите пароль подключения");
        if (settings.VkHashMode != "auto_js" && string.IsNullOrWhiteSpace(settings.VkHashes)) throw new ArgumentException("Укажите хеши VK");
        if (settings.VkHashMode == "auto_js") throw new NotSupportedException("Auto JS пока не включён в Windows UI. Выберите ручные хеши VK.");
    }

    public void Dispose() => DisconnectAsync().GetAwaiter().GetResult();

    private sealed record DefaultRoute(uint InterfaceIndex, string NextHop);
}

internal static class StringExtensions
{
    public static string OrEmpty(this string? value) => value ?? "";
}
