using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace VPNSL.Windows;

internal sealed class VpnEngine : IDisposable
{
    private const int DefaultPeerPort = 46000;

    private readonly object _gate = new();
    private readonly object _stdinGate = new();
    private readonly SemaphoreSlim _routeMutation = new(1, 1);
    private CancellationTokenSource? _cancellation;
    private Process? _client;
    private WintunAdapter? _wintun;
    private readonly List<RouteInstall> _installedRoutes = [];
    private TaskCompletionSource<(string Ip, string Dns)>? _configSource;
    private string? _lastClientError;
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
            _lastClientError = null;
        }

        var token = sessionCancellation.Token;
        try
        {
            Validate(settings);
            settings.Peer = NormalizePeer(settings.Peer, settings.ServerPeerPort);

            StatusChanged?.Invoke("Подключение");
            Log?.Invoke("[WINDOWS] Запуск VPNSL 1.0.8");
            Log?.Invoke($"[WINDOWS] Peer: {settings.Peer}");

            var physical = await GetPhysicalDefaultRouteAsync(0, token);
            var port = FindFreeUdpPort();
            StartClient(settings, port, token);

            var config = await _configSource!.Task.WaitAsync(token);
            Log?.Invoke($"[WINDOWS] Получена конфигурация TUN: {config.Ip}/32, DNS {config.Dns}");

            token.ThrowIfCancellationRequested();
            _wintun = new WintunAdapter();
            _wintun.Open();
            await ConfigureAdapterAsync(_wintun.InterfaceIndex, config.Ip, config.Dns, token);

            physical = await GetPhysicalDefaultRouteAsync(_wintun.InterfaceIndex, token) ?? physical;
            await _routeMutation.WaitAsync(token);
            try
            {
                await RemoveInstalledRoutesCoreAsync(CancellationToken.None);
                await ApplyRoutePolicyCoreAsync(settings, _wintun.InterfaceIndex, physical, token);
            }
            finally
            {
                _routeMutation.Release();
            }

            token.ThrowIfCancellationRequested();
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

    public async Task ReapplyRoutesAsync(AppSettings settings)
    {
        var wintun = _wintun;
        var cancellation = _cancellation;
        if (!_running || wintun is null || cancellation is null) return;

        var token = cancellation.Token;
        await _routeMutation.WaitAsync(token);
        try
        {
            token.ThrowIfCancellationRequested();
            Log?.Invoke("[ROUTE] Пакетное применение изменённых маршрутов…");
            await RemoveInstalledRoutesCoreAsync(CancellationToken.None);
            var physical = await GetPhysicalDefaultRouteAsync(wintun.InterfaceIndex, token);
            await ApplyRoutePolicyCoreAsync(settings, wintun.InterfaceIndex, physical, token);
            Log?.Invoke("[ROUTE] Маршруты применены без перезапуска VPN");
        }
        finally
        {
            _routeMutation.Release();
        }
    }

    public async Task DisconnectAsync()
    {
        CancellationTokenSource? cancellation;
        Process? client;
        WintunAdapter? wintun;

        lock (_gate)
        {
            cancellation = _cancellation;
            if (cancellation is null && !_running && _client is null && _wintun is null) return;
            _cancellation = null;
            _running = false;
            client = _client;
            _client = null;
            wintun = _wintun;
            _wintun = null;
        }

        StatusChanged?.Invoke("Отключение…");
        try { cancellation?.Cancel(); } catch { }

        if (client is not null)
        {
            try
            {
                if (!client.HasExited)
                {
                    TrySendControlCommand(client, "STOP");
                    var exitTask = client.WaitForExitAsync();
                    if (await Task.WhenAny(exitTask, Task.Delay(800)) != exitTask)
                    {
                        try { client.Kill(true); } catch { }
                    }
                    else
                    {
                        await exitTask;
                    }
                }
            }
            catch
            {
                try { client.Kill(true); } catch { }
            }
            try { client.Dispose(); } catch { }
        }

        if (wintun is not null)
        {
            try { await Task.Run(wintun.Dispose); }
            catch (Exception ex) { Log?.Invoke($"[WINDOWS] Wintun stop: {ex.Message}"); }
        }

        await _routeMutation.WaitAsync(CancellationToken.None);
        try
        {
            await RemoveInstalledRoutesCoreAsync(CancellationToken.None);
        }
        finally
        {
            _routeMutation.Release();
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
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            StandardInputEncoding = new UTF8Encoding(false),
            CreateNoWindow = true,
            WorkingDirectory = AppContext.BaseDirectory,
        };
        info.Environment["CSQTT_EVENTS"] = "1";
        info.Environment["CSQTT_PARENT_PID"] = Environment.ProcessId.ToString(CultureInfo.InvariantCulture);

        AddArg(info, "--listen", $"127.0.0.1:{port}");
        AddArg(info, "--peer", settings.Peer);
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
            if (token.IsCancellationRequested) return;

            var exitCode = SafeExitCode(process);
            Log?.Invoke($"[КЛИЕНТ] Процесс завершён, код {exitCode}");

            _ = Task.Run(async () =>
            {
                await Task.Delay(80).ConfigureAwait(false);
                var detail = _lastClientError;
                var message = string.IsNullOrWhiteSpace(detail)
                    ? $"client.exe завершился с кодом {exitCode} до получения конфигурации туннеля"
                    : detail;

                _configSource?.TrySetException(new InvalidOperationException(message));
                try { await DisconnectAsync().ConfigureAwait(false); }
                catch (Exception ex) { Log?.Invoke($"[WINDOWS] Очистка после остановки клиента: {ex.Message}"); }
            });
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
            if (line.Contains("[ФАТАЛ]", StringComparison.OrdinalIgnoreCase) ||
                line.Contains("[ОШИБКА]", StringComparison.OrdinalIgnoreCase) ||
                line.Contains("ошибка", StringComparison.OrdinalIgnoreCase))
            {
                _lastClientError = line;
            }
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
                    _lastClientError = message;
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

    private async Task ApplyRoutePolicyCoreAsync(
        AppSettings settings,
        uint tunnelInterface,
        DefaultRoute? physical,
        CancellationToken token)
    {
        var chosen = new Dictionary<string, RouteTarget>(StringComparer.OrdinalIgnoreCase);
        var enabledProfiles = settings.Routes.Where(p => p.Enabled).ToList();

        foreach (var profile in enabledProfiles)
        {
            foreach (var raw in profile.Routes)
            {
                if (!RoutePolicy.TryNormalize(raw, out var cidr)) continue;

                if (!chosen.TryGetValue(cidr, out var existing) ||
                    (existing != RouteTarget.VPNSL && profile.Target == RouteTarget.VPNSL))
                {
                    chosen[cidr] = profile.Target;
                }
            }
        }

        var routes = new List<RouteInstall>();
        foreach (var route in chosen.OrderByDescending(r => PrefixLength(r.Key)))
        {
            if (route.Value == RouteTarget.VPNSL)
            {
                routes.Add(new RouteInstall(route.Key, tunnelInterface, "0.0.0.0", 5));
            }
            else if (physical is not null)
            {
                routes.Add(new RouteInstall(route.Key, physical.InterfaceIndex, physical.NextHop, 1));
            }
        }

        if (physical is not null)
        {
            var host = ExtractHost(settings.Peer);
            if (host.Length > 0)
            {
                try
                {
                    var addresses = await Dns.GetHostAddressesAsync(host, token);
                    foreach (var ip in addresses.Where(x => x.AddressFamily == AddressFamily.InterNetwork))
                    {
                        var prefix = $"{ip}/32";
                        if (!routes.Any(r => r.Prefix.Equals(prefix, StringComparison.OrdinalIgnoreCase) && r.InterfaceIndex == physical.InterfaceIndex))
                            routes.Add(new RouteInstall(prefix, physical.InterfaceIndex, physical.NextHop, 0));
                    }
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Log?.Invoke($"[ROUTE] Не удалось защитить адрес peer от зацикливания: {ex.Message}");
                }
            }
        }

        await InstallRoutesBulkAsync(routes, token);

        var vpnCount = chosen.Count(x => x.Value == RouteTarget.VPNSL);
        var physicalCount = chosen.Count - vpnCount;
        Log?.Invoke($"[ROUTE] Активно правил: {chosen.Count}; через VPNSL: {vpnCount}; через обычную сеть: {physicalCount}");

        foreach (var profile in enabledProfiles)
            Log?.Invoke($"[ROUTE] Профиль «{profile.Name}»: {profile.Target}, маршрутов {profile.Routes.Count}");
    }

    private async Task InstallRoutesBulkAsync(IReadOnlyCollection<RouteInstall> routes, CancellationToken token)
    {
        if (routes.Count == 0) return;

        Log?.Invoke($"[ROUTE] Пакетная установка маршрутов: {routes.Count}");
        var script = new StringBuilder();
        script.AppendLine("$ErrorActionPreference = 'Stop'");
        foreach (var route in routes)
        {
            var prefix = Ps(route.Prefix);
            var nextHop = Ps(route.NextHop);
            script.AppendLine($"Remove-NetRoute -DestinationPrefix '{prefix}' -InterfaceIndex {route.InterfaceIndex} -Confirm:$false -ErrorAction SilentlyContinue");
            script.AppendLine($"New-NetRoute -DestinationPrefix '{prefix}' -InterfaceIndex {route.InterfaceIndex} -NextHop '{nextHop}' -RouteMetric {route.Metric} -PolicyStore ActiveStore -ErrorAction Stop | Out-Null");
        }

        await PowerShellScriptAsync(script.ToString(), token);
        _installedRoutes.AddRange(routes);
        Log?.Invoke($"[ROUTE] Пакетная установка завершена: {routes.Count}");
    }

    private async Task RemoveInstalledRoutesCoreAsync(CancellationToken token)
    {
        if (_installedRoutes.Count == 0) return;

        var installed = _installedRoutes
            .DistinctBy(r => (r.Prefix.ToUpperInvariant(), r.InterfaceIndex))
            .ToArray();
        _installedRoutes.Clear();

        Log?.Invoke($"[ROUTE] Пакетное удаление маршрутов: {installed.Length}");
        var script = new StringBuilder();
        script.AppendLine("$ErrorActionPreference = 'SilentlyContinue'");

        var groupNumber = 0;
        foreach (var group in installed.GroupBy(r => r.InterfaceIndex))
        {
            var table = "$wanted" + groupNumber++;
            script.AppendLine($"{table} = @{{}}");
            foreach (var route in group)
                script.AppendLine($"{table}['{Ps(route.Prefix)}'] = $true");
            script.AppendLine($"Get-NetRoute -InterfaceIndex {group.Key} -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {{ {table}.ContainsKey($_.DestinationPrefix) }} | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue");
        }

        try
        {
            await PowerShellScriptAsync(script.ToString(), token);
            Log?.Invoke($"[ROUTE] Пакетное удаление завершено: {installed.Length}");
        }
        catch (Exception ex)
        {
            Log?.Invoke($"[ROUTE] Ошибка пакетного удаления: {ex.Message}");
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
        using var registration = token.Register(() => TryKill(process));
        var stdoutTask = process.StandardOutput.ReadToEndAsync(token);
        var stderrTask = process.StandardError.ReadToEndAsync(token);
        await process.WaitForExitAsync(token);
        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        if (process.ExitCode != 0) throw new InvalidOperationException(stderr.Trim().Length > 0 ? stderr.Trim() : $"PowerShell exit {process.ExitCode}");
        return stdout;
    }

    private static async Task<string> PowerShellScriptAsync(string script, CancellationToken token)
    {
        var info = new ProcessStartInfo("powershell.exe")
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            StandardInputEncoding = new UTF8Encoding(false),
            CreateNoWindow = true,
        };
        info.ArgumentList.Add("-NoProfile");
        info.ArgumentList.Add("-NonInteractive");
        info.ArgumentList.Add("-ExecutionPolicy");
        info.ArgumentList.Add("Bypass");
        info.ArgumentList.Add("-Command");
        info.ArgumentList.Add("-");

        using var process = Process.Start(info) ?? throw new InvalidOperationException("Не удалось запустить PowerShell");
        using var registration = token.Register(() => TryKill(process));
        await process.StandardInput.WriteAsync(script.AsMemory(), token);
        process.StandardInput.Close();
        var stdoutTask = process.StandardOutput.ReadToEndAsync(token);
        var stderrTask = process.StandardError.ReadToEndAsync(token);
        await process.WaitForExitAsync(token);
        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        if (process.ExitCode != 0) throw new InvalidOperationException(stderr.Trim().Length > 0 ? stderr.Trim() : $"PowerShell exit {process.ExitCode}");
        return stdout;
    }

    private static void TryKill(Process process)
    {
        try { if (!process.HasExited) process.Kill(true); } catch { }
    }

    private static bool TryParseTunConfig(string value, out string ip, out string dns)
    {
        ip = dns = "";
        if (!value.StartsWith("TUNCONF:", StringComparison.Ordinal)) return false;
        var parts = value[8..].Split(':', 3);
        if (parts.Length < 2 ||
            !IPAddress.TryParse(parts[0], out var ipAddress) ||
            ipAddress.AddressFamily != AddressFamily.InterNetwork ||
            !IPAddress.TryParse(parts[1], out var dnsAddress) ||
            dnsAddress.AddressFamily != AddressFamily.InterNetwork)
            return false;
        ip = parts[0];
        dns = parts[1];
        return true;
    }

    private static string NormalizePeer(string rawPeer, int configuredDefaultPort)
    {
        var text = rawPeer.Trim();
        if (text.Length == 0) return text;

        var defaultPort = configuredDefaultPort is >= 1 and <= 65535 ? configuredDefaultPort : DefaultPeerPort;

        if (text.Contains("://", StringComparison.Ordinal))
        {
            if (!Uri.TryCreate(text, UriKind.Absolute, out var uri) || string.IsNullOrWhiteSpace(uri.Host))
                throw new ArgumentException("Некорректный Peer. Укажите IP/домен или IP/домен:порт.");

            var port = uri.IsDefaultPort ? defaultPort : uri.Port;
            return FormatPeer(uri.Host, port);
        }

        if (IPAddress.TryParse(text, out var literalAddress))
            return FormatPeer(literalAddress.ToString(), defaultPort);

        if (text.StartsWith("[", StringComparison.Ordinal))
        {
            var close = text.IndexOf(']');
            if (close <= 1) throw new ArgumentException("Некорректный IPv6 Peer.");
            var host = text[1..close];
            if (!IPAddress.TryParse(host, out _)) throw new ArgumentException("Некорректный IPv6 Peer.");
            var remainder = text[(close + 1)..];
            if (remainder.Length == 0) return FormatPeer(host, defaultPort);
            if (!remainder.StartsWith(':') || !TryParsePort(remainder[1..], out var ipv6Port))
                throw new ArgumentException("Некорректный порт Peer. Допустимо 1–65535.");
            return FormatPeer(host, ipv6Port);
        }

        var firstColon = text.IndexOf(':');
        var lastColon = text.LastIndexOf(':');
        if (firstColon >= 0)
        {
            if (firstColon != lastColon)
                throw new ArgumentException("IPv6 Peer указывайте в формате [адрес]:порт.");

            var host = text[..firstColon].Trim();
            var portText = text[(firstColon + 1)..].Trim();
            if (host.Length == 0) throw new ArgumentException("В Peer отсутствует IP или домен.");
            if (!TryParsePort(portText, out var port))
                throw new ArgumentException("Некорректный порт Peer. Допустимо 1–65535.");
            ValidateHostText(host);
            return $"{host}:{port}";
        }

        ValidateHostText(text);
        return $"{text}:{defaultPort}";
    }

    private static bool TryParsePort(string value, out int port) =>
        int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out port) && port is >= 1 and <= 65535;

    private static void ValidateHostText(string host)
    {
        if (host.Any(char.IsWhiteSpace) || host.Contains('/') || host.Contains('\\') || host.Contains('?') || host.Contains('#'))
            throw new ArgumentException("Некорректный Peer. Укажите только IP/домен и необязательный порт.");
    }

    private static string FormatPeer(string host, int port) =>
        IPAddress.TryParse(host, out var address) && address.AddressFamily == AddressFamily.InterNetworkV6
            ? $"[{host}]:{port}"
            : $"{host}:{port}";

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

    public void Dispose()
    {
        try { DisconnectAsync().GetAwaiter().GetResult(); } catch { }
        _routeMutation.Dispose();
    }

    private sealed record DefaultRoute(uint InterfaceIndex, string NextHop);
    private sealed record RouteInstall(string Prefix, uint InterfaceIndex, string NextHop, int Metric);
}

internal static class StringExtensions
{
    public static string OrEmpty(this string? value) => value ?? "";
}
