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
    private const int RouteBatchSize = 128;
    private const string TurnConnectMarker = "[TURN] Подключение к ";
    private const string TurnCredentialMarker = "OK, TURN: ";
    private static readonly TimeSpan TransportDiscoveryTimeout = TimeSpan.FromSeconds(4);

    private readonly object _gate = new();
    private readonly object _stdinGate = new();
    private readonly object _transportGate = new();
    private readonly SemaphoreSlim _routeMutation = new(1, 1);
    private readonly HashSet<string> _transportHosts = new(StringComparer.OrdinalIgnoreCase);
    private CancellationTokenSource? _cancellation;
    private Process? _client;
    private WintunAdapter? _wintun;
    private readonly List<RouteInstall> _installedRoutes = [];
    private TaskCompletionSource<(string Ip, string Dns)>? _configSource;
    private TaskCompletionSource<bool>? _transportReadySource;
    private DefaultRoute? _physicalDefault;
    private string? _lastClientError;
    private bool _fullTunnelReady;
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
            _transportReadySource = new(TaskCreationOptions.RunContinuationsAsynchronously);
            _lastClientError = null;
            _fullTunnelReady = false;
            _physicalDefault = null;
        }
        lock (_transportGate) _transportHosts.Clear();

        var token = sessionCancellation.Token;
        try
        {
            Validate(settings);
            settings.Peer = NormalizePeer(settings.Peer, settings.ServerPeerPort);

            StatusChanged?.Invoke("Подключение");
            Log?.Invoke("[WINDOWS] Запуск VPNSL");
            Log?.Invoke($"[WINDOWS] Peer: {settings.Peer}");
            Log?.Invoke("[ROUTE] Режим: весь IPv4-трафик через VPNSL; профили «Напрямую» работают как исключения");

            var physical = await GetPhysicalDefaultRouteAsync(0, token)
                ?? throw new InvalidOperationException(
                    "Не найден физический IPv4-маршрут по умолчанию. Full-tunnel нельзя включить безопасно.");
            _physicalDefault = physical;
            Log?.Invoke($"[ROUTE] Физический шлюз: ifIndex={physical.InterfaceIndex}, nextHop={physical.NextHop}");

            if (!string.IsNullOrWhiteSpace(settings.TurnHost))
                RegisterTransportHost(ExtractTransportHost(settings.TurnHost), confirmsTransport: true);

            var port = FindFreeUdpPort();
            StartClient(settings, port, token);

            var config = await _configSource!.Task.WaitAsync(token);
            Log?.Invoke($"[WINDOWS] Получена конфигурация TUN: {config.Ip}/32, DNS {config.Dns}");

            // CONFIG comes from a working TURN allocation. Before changing the
            // Windows default path we must know at least one TURN endpoint and
            // protect it with a physical /32 route. stdout/stderr are separate
            // pipes, so the CONFIG event can otherwise overtake earlier TURN
            // log lines and the client immediately routes its own transport
            // back into Wintun.
            await WaitForTransportDiscoveryAsync(token);

            token.ThrowIfCancellationRequested();
            _wintun = new WintunAdapter();
            _wintun.Open();
            await ConfigureAdapterAsync(_wintun.InterfaceIndex, config.Ip, config.Dns, token);
            await RemoveStaleFullTunnelRoutesAsync(_wintun.InterfaceIndex, token);

            physical = await GetPhysicalDefaultRouteAsync(_wintun.InterfaceIndex, token) ?? physical;
            _physicalDefault = physical;

            token.ThrowIfCancellationRequested();
            _wintun.StartBridge(port, message => Log?.Invoke(message), token);

            var routeSettings = CloneRoutingSettings(settings);
            await _routeMutation.WaitAsync(token);
            try
            {
                await RemoveInstalledRoutesCoreAsync(CancellationToken.None);
                Log?.Invoke("[ROUTE] Включение full-tunnel и пользовательских правил…");
                await ApplyRoutePolicyCoreAsync(routeSettings, _wintun.InterfaceIndex, physical, token);
            }
            finally
            {
                _routeMutation.Release();
            }

            _fullTunnelReady = true;
            _running = true;
            StatusChanged?.Invoke("Подключено");
            Log?.Invoke($"[WINDOWS] Wintun активен, interface index {_wintun.InterfaceIndex}");
            Log?.Invoke("[ROUTE] Full-tunnel активен: весь IPv4-трафик по умолчанию направлен через VPNSL");

            _ = Task.Run(EnsureAllTransportBypassesAsync, CancellationToken.None);
            _ = Task.Run(() => LogBridgeHealthAsync(_wintun, token), CancellationToken.None);
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
        var snapshot = CloneRoutingSettings(settings);
        await _routeMutation.WaitAsync(token);
        try
        {
            token.ThrowIfCancellationRequested();
            Log?.Invoke("[ROUTE] Применение изменённых маршрутов…");
            await RemoveInstalledRoutesCoreAsync(CancellationToken.None);
            var physical = await GetPhysicalDefaultRouteAsync(wintun.InterfaceIndex, token)
                ?? _physicalDefault
                ?? throw new InvalidOperationException("Не найден физический маршрут для исключений из VPN.");
            _physicalDefault = physical;
            await ApplyRoutePolicyCoreAsync(snapshot, wintun.InterfaceIndex, physical, token);
            Log?.Invoke("[ROUTE] Маршруты применены без перезапуска VPN");
        }
        finally
        {
            _routeMutation.Release();
        }

        _ = Task.Run(EnsureAllTransportBypassesAsync, CancellationToken.None);
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
            _fullTunnelReady = false;
            client = _client;
            _client = null;
            wintun = _wintun;
            _wintun = null;
        }

        StatusChanged?.Invoke("Отключение…");
        try { cancellation?.Cancel(); } catch { }

        await _routeMutation.WaitAsync(CancellationToken.None);
        try
        {
            await RemoveInstalledRoutesCoreAsync(CancellationToken.None);
        }
        finally
        {
            _routeMutation.Release();
        }

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

        _physicalDefault = null;
        lock (_transportGate) _transportHosts.Clear();
        cancellation?.Dispose();
        _configSource?.TrySetCanceled();
        _configSource = null;
        _transportReadySource?.TrySetCanceled();
        _transportReadySource = null;
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
            TryCaptureCredentialTransportEndpoints(line);
            TryCaptureTransportEndpoint(line);
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

    private void TryCaptureCredentialTransportEndpoints(string line)
    {
        var marker = line.IndexOf(TurnCredentialMarker, StringComparison.Ordinal);
        if (marker < 0 || !line.Contains("[КРЕД #", StringComparison.Ordinal)) return;

        try
        {
            var arrayStart = line.IndexOf('[', marker + TurnCredentialMarker.Length);
            var arrayEnd = line.LastIndexOf(']');
            if (arrayStart < 0 || arrayEnd <= arrayStart) return;

            using var document = JsonDocument.Parse(line[arrayStart..(arrayEnd + 1)]);
            if (document.RootElement.ValueKind != JsonValueKind.Array) return;
            foreach (var element in document.RootElement.EnumerateArray())
            {
                if (element.ValueKind != JsonValueKind.String) continue;
                RegisterTransportHost(ExtractTransportHost(element.GetString().OrEmpty()), confirmsTransport: true);
            }
        }
        catch
        {
            // The dedicated [TURN] line below is a second discovery path.
        }
    }

    private void TryCaptureTransportEndpoint(string line)
    {
        var marker = line.IndexOf(TurnConnectMarker, StringComparison.Ordinal);
        if (marker < 0) return;
        var endpoint = line[(marker + TurnConnectMarker.Length)..].Trim();
        var host = ExtractTransportHost(endpoint);
        RegisterTransportHost(host, confirmsTransport: true);
    }

    private void RegisterTransportHost(string host, bool confirmsTransport)
    {
        if (string.IsNullOrWhiteSpace(host)) return;
        var normalized = host.Trim();
        var added = false;
        lock (_transportGate) added = _transportHosts.Add(normalized);

        if (confirmsTransport)
            _transportReadySource?.TrySetResult(true);

        if (!added) return;
        Log?.Invoke($"[ROUTE] Транспорт VPNSL: {normalized}");
        if (_fullTunnelReady)
            _ = Task.Run(() => EnsureTransportBypassAsync(normalized), CancellationToken.None);
    }

    private async Task WaitForTransportDiscoveryAsync(CancellationToken token)
    {
        var source = _transportReadySource;
        if (source is null) throw new InvalidOperationException("Не инициализирован контроль TURN-маршрута.");
        if (!source.Task.IsCompleted)
        {
            Log?.Invoke("[ROUTE] Ожидание адреса TURN перед включением full-tunnel…");
            var delay = Task.Delay(TransportDiscoveryTimeout, token);
            var completed = await Task.WhenAny(source.Task, delay);
            token.ThrowIfCancellationRequested();
            if (completed != source.Task)
            {
                throw new InvalidOperationException(
                    "Не удалось определить TURN-адрес VPNSL до включения full-tunnel. " +
                    "Маршрутизация не изменена, чтобы не зациклить транспорт VPN.");
            }
        }

        await source.Task.WaitAsync(token);
        string[] hosts;
        lock (_transportGate) hosts = _transportHosts.ToArray();
        if (hosts.Length == 0)
            throw new InvalidOperationException("TURN-транспорт подтверждён, но адрес для физического обхода не найден.");
        Log?.Invoke($"[ROUTE] TURN-защита подготовлена: {string.Join(", ", hosts)}");
    }

    private async Task EnsureAllTransportBypassesAsync()
    {
        string[] hosts;
        lock (_transportGate) hosts = _transportHosts.ToArray();
        foreach (var host in hosts)
            await EnsureTransportBypassAsync(host).ConfigureAwait(false);
    }

    private async Task EnsureTransportBypassAsync(string host)
    {
        if (!_fullTunnelReady) return;
        var physical = _physicalDefault;
        if (physical is null) return;

        IReadOnlyList<IPAddress> addresses;
        try
        {
            addresses = await ResolveIpv4Async(host, CancellationToken.None).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            Log?.Invoke($"[ROUTE] Не удалось разрешить транспорт {host}: {ex.Message}");
            return;
        }

        if (addresses.Count == 0) return;
        await _routeMutation.WaitAsync(CancellationToken.None).ConfigureAwait(false);
        try
        {
            if (!_fullTunnelReady) return;
            var additions = addresses
                .Select(ip => new RouteInstall($"{ip}/32", physical.InterfaceIndex, physical.NextHop, 0))
                .Where(route => !_installedRoutes.Any(existing =>
                    existing.InterfaceIndex == route.InterfaceIndex &&
                    string.Equals(existing.Prefix, route.Prefix, StringComparison.OrdinalIgnoreCase)))
                .ToArray();
            if (additions.Length == 0) return;
            await InstallRoutesBulkAsync(additions, CancellationToken.None).ConfigureAwait(false);
            Log?.Invoke($"[ROUTE] Транспортный обход добавлен: {host} → {string.Join(", ", additions.Select(x => x.Prefix))}");
        }
        catch (Exception ex)
        {
            Log?.Invoke($"[ROUTE] Ошибка транспортного обхода {host}: {ex.Message}");
        }
        finally
        {
            _routeMutation.Release();
        }
    }

    private async Task ApplyRoutePolicyCoreAsync(
        AppSettings settings,
        uint tunnelInterface,
        DefaultRoute physical,
        CancellationToken token)
    {
        var chosen = new Dictionary<string, RouteTarget>(StringComparer.OrdinalIgnoreCase);
        var enabledProfiles = settings.Routes.Where(p => p.Enabled).ToList();

        foreach (var profile in enabledProfiles)
        {
            foreach (var raw in profile.Routes)
            {
                if (!RoutePolicy.TryNormalize(raw, out var cidr)) continue;

                // Full-tunnel is already the default. On an exact duplicate,
                // a direct rule is the meaningful exception and therefore wins.
                if (!chosen.TryGetValue(cidr, out var existing) ||
                    (existing != RouteTarget.MOBILE && profile.Target == RouteTarget.MOBILE))
                {
                    chosen[cidr] = profile.Target;
                }
            }
        }

        var routes = new List<RouteInstall>();
        string[] transportHosts;
        lock (_transportGate) transportHosts = _transportHosts.ToArray();
        if (transportHosts.Length == 0)
            throw new InvalidOperationException("Full-tunnel отменён: не найден ни один TURN-адрес для обхода Wintun.");

        var protectedHosts = new HashSet<string>(transportHosts, StringComparer.OrdinalIgnoreCase);
        var peerHost = ExtractHost(settings.Peer);
        if (peerHost.Length > 0) protectedHosts.Add(peerHost);
        if (!string.IsNullOrWhiteSpace(settings.TurnHost))
        {
            var turnHost = ExtractTransportHost(settings.TurnHost);
            if (turnHost.Length > 0) protectedHosts.Add(turnHost);
        }

        var transportIpv4Routes = 0;
        foreach (var host in protectedHosts)
        {
            try
            {
                var addresses = await ResolveIpv4Async(host, token);
                foreach (var ip in addresses)
                {
                    routes.Add(new RouteInstall($"{ip}/32", physical.InterfaceIndex, physical.NextHop, 0));
                    if (transportHosts.Contains(host, StringComparer.OrdinalIgnoreCase))
                        transportIpv4Routes++;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Log?.Invoke($"[ROUTE] Не удалось защитить транспортный адрес {host}: {ex.Message}");
            }
        }

        if (transportIpv4Routes == 0)
        {
            var onlyIpv6 = transportHosts.All(host =>
                IPAddress.TryParse(host, out var ip) && ip.AddressFamily == AddressFamily.InterNetworkV6);
            if (!onlyIpv6)
                throw new InvalidOperationException(
                    "Full-tunnel отменён: TURN-адреса найдены, но ни один IPv4-обход через физический шлюз не удалось подготовить.");
        }

        // Two /1 routes are more specific than the physical 0.0.0.0/0 route.
        // This keeps the physical default route intact while making VPNSL the
        // default path for all public IPv4 traffic. More specific direct rules
        // (/8, /24, /32, etc.) still override these routes naturally.
        routes.Add(new RouteInstall("0.0.0.0/1", tunnelInterface, "0.0.0.0", 5));
        routes.Add(new RouteInstall("128.0.0.0/1", tunnelInterface, "0.0.0.0", 5));

        foreach (var route in chosen.OrderByDescending(r => PrefixLength(r.Key)))
        {
            if (route.Value == RouteTarget.VPNSL)
                routes.Add(new RouteInstall(route.Key, tunnelInterface, "0.0.0.0", 5));
            else
                routes.Add(new RouteInstall(route.Key, physical.InterfaceIndex, physical.NextHop, 1));
        }

        routes = routes
            .DistinctBy(r => (r.Prefix.ToUpperInvariant(), r.InterfaceIndex, r.NextHop))
            .ToList();

        await InstallRoutesBulkAsync(routes, token);
        await VerifyFullTunnelRoutesAsync(tunnelInterface, token);

        var explicitVpnCount = chosen.Count(x => x.Value == RouteTarget.VPNSL);
        var directCount = chosen.Count - explicitVpnCount;
        Log?.Invoke($"[ROUTE] Full-tunnel IPv4: ON; TURN IPv4-обходов: {transportIpv4Routes}; явных правил через VPNSL: {explicitVpnCount}; исключений «Напрямую»: {directCount}");

        foreach (var profile in enabledProfiles)
            Log?.Invoke($"[ROUTE] Профиль «{profile.Name}»: {profile.TargetDisplay}, маршрутов {profile.Routes.Count}");
    }

    private async Task InstallRoutesBulkAsync(IReadOnlyList<RouteInstall> routes, CancellationToken token)
    {
        if (routes.Count == 0)
        {
            Log?.Invoke("[ROUTE] Активных маршрутов нет");
            return;
        }

        Log?.Invoke($"[ROUTE] Установка/проверка маршрутов: {routes.Count}, пачками по {RouteBatchSize}");
        var completed = 0;

        foreach (var chunk in routes.Chunk(RouteBatchSize))
        {
            token.ThrowIfCancellationRequested();
            var batch = chunk.ToArray();
            _installedRoutes.AddRange(batch);

            var script = new StringBuilder();
            script.AppendLine("$ErrorActionPreference = 'Stop'");
            script.AppendLine("try {");
            foreach (var route in batch)
            {
                var prefix = Ps(route.Prefix);
                var nextHop = Ps(route.NextHop);
                script.AppendLine($"  $existing = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '{prefix}' -InterfaceIndex {route.InterfaceIndex} -ErrorAction SilentlyContinue | Where-Object {{ $_.NextHop -eq '{nextHop}' }})");
                script.AppendLine("  if ($existing.Count -eq 0) {");
                script.AppendLine($"    New-NetRoute -DestinationPrefix '{prefix}' -InterfaceIndex {route.InterfaceIndex} -NextHop '{nextHop}' -RouteMetric {route.Metric} -PolicyStore ActiveStore -ErrorAction Stop | Out-Null");
                script.AppendLine("  }");
                script.AppendLine($"  $verify = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '{prefix}' -InterfaceIndex {route.InterfaceIndex} -ErrorAction SilentlyContinue | Where-Object {{ $_.NextHop -eq '{nextHop}' }})");
                script.AppendLine($"  if ($verify.Count -eq 0) {{ throw 'Маршрут {prefix} через ifIndex {route.InterfaceIndex} не появился в таблице Windows' }}");
            }
            script.AppendLine("} catch {");
            script.AppendLine("  Write-Error $_.Exception.Message");
            script.AppendLine("  exit 1");
            script.AppendLine("}");

            await PowerShellScriptAsync(script.ToString(), token);
            completed += batch.Length;
            Log?.Invoke($"[ROUTE] Проверено маршрутов: {completed}/{routes.Count}");
        }

        Log?.Invoke($"[ROUTE] Установка и проверка маршрутов завершена: {routes.Count}");
    }

    private async Task VerifyFullTunnelRoutesAsync(uint tunnelInterface, CancellationToken token)
    {
        var command =
            $"$a = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/1' -InterfaceIndex {tunnelInterface} -ErrorAction SilentlyContinue | Where-Object {{ $_.NextHop -eq '0.0.0.0' }}); " +
            $"$b = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '128.0.0.0/1' -InterfaceIndex {tunnelInterface} -ErrorAction SilentlyContinue | Where-Object {{ $_.NextHop -eq '0.0.0.0' }}); " +
            "if ($a.Count -eq 0 -or $b.Count -eq 0) { Write-Error 'Windows не установил split-default маршруты VPNSL'; exit 1 }; " +
            "Write-Output 'FULL_TUNNEL_OK'";
        var output = await PowerShellAsync(command, token);
        if (!output.Contains("FULL_TUNNEL_OK", StringComparison.Ordinal))
            throw new InvalidOperationException("Не удалось подтвердить full-tunnel маршруты Windows.");
        Log?.Invoke($"[ROUTE] Split-default маршруты подтверждены на ifIndex {tunnelInterface}");
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
            $"Set-NetIPInterface -InterfaceIndex {index} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 5 -ErrorAction Stop";
        await PowerShellAsync(command, token);
        Log?.Invoke($"[WINTUN] IPv4 настроен: {ip}/32, DNS {dns}, ifIndex {index}");
    }

    private static async Task RemoveStaleFullTunnelRoutesAsync(uint tunnelInterface, CancellationToken token)
    {
        var command =
            "$wanted = @('0.0.0.0/1','128.0.0.0/1'); " +
            $"Get-NetRoute -InterfaceIndex {tunnelInterface} -AddressFamily IPv4 -ErrorAction SilentlyContinue | " +
            "Where-Object { $wanted -contains $_.DestinationPrefix } | " +
            "Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue";
        await PowerShellAsync(command, token);
    }

    private static async Task<DefaultRoute?> GetPhysicalDefaultRouteAsync(uint excludedInterface, CancellationToken token)
    {
        var command =
            "$items = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | " +
            $"Where-Object {{ $_.InterfaceIndex -ne {excludedInterface} -and $_.NextHop -ne '0.0.0.0' }} | ForEach-Object {{ " +
            "$if = Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue; " +
            "$cost = [int]$_.RouteMetric + [int]($if.InterfaceMetric); " +
            "[PSCustomObject]@{ Route = $_; Cost = $cost } }; " +
            "$x = $items | Sort-Object Cost | Select-Object -First 1; " +
            "if ($x) { Write-Output ($x.Route.InterfaceIndex.ToString() + '|' + $x.Route.NextHop) }";
        var output = (await PowerShellAsync(command, token)).Trim();
        var parts = output.Split('|', 2);
        return parts.Length == 2 && uint.TryParse(parts[0], out var index) && parts[1].Length > 0
            ? new DefaultRoute(index, parts[1])
            : null;
    }

    private async Task LogBridgeHealthAsync(WintunAdapter wintun, CancellationToken token)
    {
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(8), token);
            var up = wintun.TunToClientPackets;
            var down = wintun.ClientToTunPackets;
            if (up > 0 && down == 0)
                Log?.Invoke($"[WINTUN] Диагностика: отправлено в VPN {up} пакетов, ответных пока 0 — проверьте TURN/маршрут транспорта");
            else if (up > 0)
                Log?.Invoke($"[WINTUN] Диагностика: мост передаёт пакеты в обе стороны (↑ {up}, ↓ {down})");
        }
        catch (OperationCanceledException)
        {
        }
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

    private static string ExtractTransportHost(string endpoint)
    {
        var text = endpoint.Trim().Trim('"', '\'');
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

    private static async Task<IReadOnlyList<IPAddress>> ResolveIpv4Async(string host, CancellationToken token)
    {
        if (IPAddress.TryParse(host, out var literal))
            return literal.AddressFamily == AddressFamily.InterNetwork ? [literal] : [];

        return (await Dns.GetHostAddressesAsync(host, token))
            .Where(address => address.AddressFamily == AddressFamily.InterNetwork)
            .Distinct()
            .ToArray();
    }

    private static AppSettings CloneRoutingSettings(AppSettings settings) => new()
    {
        Peer = settings.Peer,
        TurnHost = settings.TurnHost,
        Routes = settings.Routes.Select(profile => new RouteProfile
        {
            Id = profile.Id,
            Name = profile.Name,
            Enabled = profile.Enabled,
            Target = profile.Target,
            Routes = [.. profile.Routes],
        }).ToList(),
    };

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
