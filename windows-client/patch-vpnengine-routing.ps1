param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$text = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8

# Keep Wintun eligible for an explicit default route if Windows removes the
# usual def1 (/1 + /1) pair after NetTCPIP/CIM creates it.
$text = $text.Replace(
    'Set-NetIPInterface -InterfaceIndex {index} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 5 -ErrorAction Stop',
    'Set-NetIPInterface -InterfaceIndex {index} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 5 -IgnoreDefaultRoutes Disabled -ErrorAction Stop')

# Clean a possible fallback /0 left from an interrupted previous session too.
$text = $text.Replace(
    '$wanted = @(''0.0.0.0/1'',''128.0.0.0/1''); ',
    '$wanted = @(''0.0.0.0/0'',''0.0.0.0/1'',''128.0.0.0/1''); ')

# Direct profiles are resolved while the physical default route is still
# available. A file called e.g. ozon.ru.bat therefore gets fresh /32 routes for
# the current root/www A records in addition to its static CIDRs.
$routesMarker = '        var routes = new List<RouteInstall>();'
$routesReplacement = @'
        foreach (var profile in enabledProfiles.Where(profile => profile.Target == RouteTarget.MOBILE))
        {
            if (!TryInferDirectProfileHost(profile.Name, out var directHost)) continue;

            var liveHosts = directHost.StartsWith("www.", StringComparison.OrdinalIgnoreCase)
                ? new[] { directHost }
                : new[] { directHost, "www." + directHost };

            foreach (var liveHost in liveHosts.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                try
                {
                    var liveAddresses = await ResolveIpv4Async(liveHost, token);
                    if (liveAddresses.Count == 0) continue;

                    foreach (var ip in liveAddresses)
                        chosen[$"{ip}/32"] = RouteTarget.MOBILE;

                    Log?.Invoke($"[ROUTE] LIVE-DNS «{profile.Name}»: {liveHost} → {string.Join(", ", liveAddresses.Select(ip => ip.ToString()))}");
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Log?.Invoke($"[ROUTE] LIVE-DNS «{profile.Name}»: {liveHost}: {ex.Message}");
                }
            }
        }

        var routes = new List<RouteInstall>();
        var userDirectRoutes = new List<RouteInstall>();
'@
if (-not $text.Contains($routesMarker)) {
    throw 'Route list marker was not found; source layout changed.'
}
$text = $text.Replace($routesMarker, $routesReplacement.TrimEnd("`r", "`n"))

# Do not install user direct routes in the same batch as full-tunnel. On hosts
# that replace /1 routes with the fallback /0 this created a race where the
# exclusions could be lost while the final default route was being established.
$directMarker = @'
            if (route.Value == RouteTarget.MOBILE)
                routes.Add(new RouteInstall(route.Key, physical.InterfaceIndex, physical.NextHop, 1));
'@
$directReplacement = @'
            if (route.Value == RouteTarget.MOBILE)
                userDirectRoutes.Add(new RouteInstall(route.Key, physical.InterfaceIndex, physical.NextHop, 1));
'@
if (-not $text.Contains($directMarker.TrimEnd("`r", "`n"))) {
    throw 'Direct route collection marker was not found; source layout changed.'
}
$text = $text.Replace($directMarker.TrimEnd("`r", "`n"), $directReplacement.TrimEnd("`r", "`n"))

$verifyCallMarker = @'
        await InstallRoutesBulkAsync(routes, token);
        await VerifyFullTunnelRoutesAsync(tunnelInterface, token);
'@
$verifyCallReplacement = @'
        await InstallRoutesBulkAsync(routes, token);
        await VerifyFullTunnelRoutesAsync(tunnelInterface, token);

        // Install exclusions only after Windows has settled on the final VPN
        // default route. Then verify them again from a separate process.
        if (userDirectRoutes.Count > 0)
        {
            userDirectRoutes = userDirectRoutes
                .DistinctBy(route => (route.Prefix.ToUpperInvariant(), route.InterfaceIndex, route.NextHop))
                .ToList();
            Log?.Invoke($"[ROUTE] Установка исключений «Напрямую» после full-tunnel: {userDirectRoutes.Count}");
            await InstallRoutesBulkAsync(userDirectRoutes, token);
            await VerifyAndReassertDirectRoutesAsync(userDirectRoutes, token);
        }
'@
if (-not $text.Contains($verifyCallMarker.TrimEnd("`r", "`n"))) {
    throw 'Full-tunnel verification call marker was not found; source layout changed.'
}
$text = $text.Replace($verifyCallMarker.TrimEnd("`r", "`n"), $verifyCallReplacement.TrimEnd("`r", "`n"))

$replacement = @'
    private async Task VerifyFullTunnelRoutesAsync(uint tunnelInterface, CancellationToken token)
    {
        await Task.Delay(450, token);
        var lastOutput = await QueryFullTunnelRouteStateAsync(tunnelInterface, token);
        if (lastOutput.Contains("FULL_TUNNEL_OK", StringComparison.Ordinal))
        {
            Log?.Invoke($"[ROUTE] Split-default маршруты подтверждены на ifIndex {tunnelInterface}: {lastOutput}");
            return;
        }

        Log?.Invoke($"[ROUTE] PowerShell split-default исчез после создания ({lastOutput}); пробуем native netsh route");

        for (var attempt = 1; attempt <= 3; attempt++)
        {
            try
            {
                await InstallSplitDefaultWithNetshAsync(tunnelInterface, token);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Log?.Invoke($"[ROUTE] netsh split-default не создан: {ex.Message}");
                break;
            }

            await Task.Delay(400, token);
            lastOutput = await QueryFullTunnelRouteStateAsync(tunnelInterface, token);
            if (lastOutput.Contains("FULL_TUNNEL_OK", StringComparison.Ordinal))
            {
                Log?.Invoke($"[ROUTE] Split-default подтверждён через netsh на ifIndex {tunnelInterface}: {lastOutput}");
                return;
            }

            Log?.Invoke($"[ROUTE] netsh split-default не удержался ({lastOutput}), попытка {attempt}/3");
        }

        Log?.Invoke("[ROUTE] /1 маршруты не удерживаются; резервный full-tunnel: 0.0.0.0/0 через Wintun");

        string? lastInstallError = null;
        for (var attempt = 1; attempt <= 4; attempt++)
        {
            try
            {
                await InstallDefaultRouteWithNetshAsync(tunnelInterface, token);
                lastInstallError = null;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                lastInstallError = ex.Message;
                Log?.Invoke($"[ROUTE] Резервный default-route: ошибка установки {attempt}/4: {ex.Message}");
            }

            await Task.Delay(400, token);
            lastOutput = await QueryFullTunnelRouteStateAsync(tunnelInterface, token);
            if (lastOutput.Contains("DEFAULT_TUNNEL_OK", StringComparison.Ordinal))
            {
                var fallback = new RouteInstall("0.0.0.0/0", tunnelInterface, "0.0.0.0", 1);
                if (!_installedRoutes.Any(route =>
                    route.InterfaceIndex == fallback.InterfaceIndex &&
                    string.Equals(route.Prefix, fallback.Prefix, StringComparison.OrdinalIgnoreCase)))
                {
                    _installedRoutes.Add(fallback);
                }

                Log?.Invoke($"[ROUTE] Full-tunnel подтверждён резервным default-route на ifIndex {tunnelInterface}: {lastOutput}");
                return;
            }
        }

        var detail = string.IsNullOrWhiteSpace(lastInstallError)
            ? lastOutput
            : $"{lastOutput}; INSTALL={lastInstallError}";
        throw new InvalidOperationException(
            $"Windows не удержал full-tunnel маршруты VPNSL на ifIndex {tunnelInterface}. Диагностика: {detail}");
    }

    private async Task VerifyAndReassertDirectRoutesAsync(
        IReadOnlyList<RouteInstall> directRoutes,
        CancellationToken token)
    {
        if (directRoutes.Count == 0) return;

        await Task.Delay(450, token);
        var missing = await QueryMissingDirectRoutesAsync(directRoutes, token);
        if (missing.Length == 0)
        {
            Log?.Invoke($"[ROUTE] DIRECT_OK: исключения «Напрямую» подтверждены {directRoutes.Count}/{directRoutes.Count}");
            return;
        }

        Log?.Invoke($"[ROUTE] DIRECT_REPAIR: после full-tunnel отсутствуют {missing.Length}/{directRoutes.Count}: {string.Join(", ", missing.Take(12))}");
        var routeByPrefix = directRoutes
            .GroupBy(route => route.Prefix, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.First(), StringComparer.OrdinalIgnoreCase);

        var repair = missing
            .Where(routeByPrefix.ContainsKey)
            .Select(prefix => routeByPrefix[prefix])
            .ToArray();

        if (repair.Length > 0)
        {
            await InstallRoutesBulkAsync(repair, token);
            await Task.Delay(400, token);
            missing = await QueryMissingDirectRoutesAsync(directRoutes, token);
        }

        if (missing.Length > 0)
        {
            Log?.Invoke($"[ROUTE] DIRECT_REPAIR: NetTCPIP не удержал {missing.Length} исключений, пробуем netsh");
            foreach (var prefix in missing)
            {
                if (!routeByPrefix.TryGetValue(prefix, out var route)) continue;
                await InstallDirectRouteWithNetshAsync(route, token);
            }

            await Task.Delay(500, token);
            missing = await QueryMissingDirectRoutesAsync(directRoutes, token);
        }

        if (missing.Length > 0)
        {
            throw new InvalidOperationException(
                $"Windows не удержал маршруты «Напрямую»: DIRECT_ROUTE_MISSING|COUNT={missing.Length}|ROUTES={string.Join(",", missing.Take(20))}");
        }

        Log?.Invoke($"[ROUTE] DIRECT_OK: исключения «Напрямую» восстановлены и подтверждены {directRoutes.Count}/{directRoutes.Count}");
    }

    private static async Task<string[]> QueryMissingDirectRoutesAsync(
        IReadOnlyList<RouteInstall> directRoutes,
        CancellationToken token)
    {
        if (directRoutes.Count == 0) return [];

        var groups = directRoutes.GroupBy(route => route.InterfaceIndex).ToArray();
        var missing = new List<string>();
        foreach (var group in groups)
        {
            var wanted = string.Join(",", group.Select(route => $"'{Ps(route.Prefix)}'"));
            var command =
                $"$wanted = @({wanted}); " +
                $"$have = @(Get-NetRoute -AddressFamily IPv4 -InterfaceIndex {group.Key} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty DestinationPrefix); " +
                "$missing = @($wanted | Where-Object { $have -notcontains $_ }); " +
                "Write-Output ($missing -join ';')";
            var output = (await PowerShellAsync(command, token)).Trim();
            if (output.Length == 0) continue;
            missing.AddRange(output.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
        }

        return missing.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static async Task InstallDirectRouteWithNetshAsync(RouteInstall route, CancellationToken token)
    {
        var prefix = Ps(route.Prefix);
        var nextHop = Ps(route.NextHop);
        var command =
            $"& netsh.exe interface ipv4 delete route prefix='{prefix}' interface={route.InterfaceIndex} store=active 2>$null | Out-Null; " +
            $"& netsh.exe interface ipv4 add route prefix='{prefix}' interface={route.InterfaceIndex} nexthop='{nextHop}' metric={route.Metric} publish=no store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }";
        await PowerShellAsync(command, token);
    }

    private static bool TryInferDirectProfileHost(string profileName, out string host)
    {
        host = "";
        if (string.IsNullOrWhiteSpace(profileName)) return false;

        var candidate = Path.GetFileName(profileName.Trim()).Trim();
        foreach (var extension in new[] { ".bat", ".txt", ".list" })
        {
            if (candidate.EndsWith(extension, StringComparison.OrdinalIgnoreCase))
            {
                candidate = candidate[..^extension.Length];
                break;
            }
        }

        candidate = candidate.Trim().TrimEnd('.');
        if (candidate.Length < 3 || candidate.Any(char.IsWhiteSpace) || !candidate.Contains('.')) return false;
        if (candidate.Contains('/') || candidate.Contains('\\') || candidate.Contains(':')) return false;
        if (Uri.CheckHostName(candidate) == UriHostNameType.Unknown) return false;

        host = candidate.ToLowerInvariant();
        return true;
    }

    private static async Task<string> QueryFullTunnelRouteStateAsync(uint tunnelInterface, CancellationToken token)
    {
        var command =
            $"$a = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/1' -InterfaceIndex {tunnelInterface} -ErrorAction SilentlyContinue); " +
            $"$b = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '128.0.0.0/1' -InterfaceIndex {tunnelInterface} -ErrorAction SilentlyContinue); " +
            $"$d = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -InterfaceIndex {tunnelInterface} -ErrorAction SilentlyContinue); " +
            "if ($a.Count -gt 0 -and $b.Count -gt 0) { Write-Output ('FULL_TUNNEL_OK|A=' + $a.Count + '|B=' + $b.Count + '|D=' + $d.Count); exit 0 }; " +
            "if ($d.Count -gt 0) { Write-Output ('DEFAULT_TUNNEL_OK|A=' + $a.Count + '|B=' + $b.Count + '|D=' + $d.Count + '|NH=' + (($d | Select-Object -ExpandProperty NextHop) -join ',')); exit 0 }; " +
            "Write-Output ('FULL_TUNNEL_MISSING|A=' + $a.Count + '|B=' + $b.Count + '|D=' + $d.Count)";
        return (await PowerShellAsync(command, token)).Trim();
    }

    private static async Task InstallSplitDefaultWithNetshAsync(uint tunnelInterface, CancellationToken token)
    {
        var command =
            $"& netsh.exe interface ipv4 delete route prefix=0.0.0.0/1 interface={tunnelInterface} store=active 2>$null | Out-Null; " +
            $"& netsh.exe interface ipv4 delete route prefix=128.0.0.0/1 interface={tunnelInterface} store=active 2>$null | Out-Null; " +
            $"& netsh.exe interface ipv4 add route prefix=0.0.0.0/1 interface={tunnelInterface} metric=5 publish=no validlifetime=infinite preferredlifetime=infinite store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; " +
            $"& netsh.exe interface ipv4 add route prefix=128.0.0.0/1 interface={tunnelInterface} metric=5 publish=no validlifetime=infinite preferredlifetime=infinite store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }";
        await PowerShellAsync(command, token);
    }

    private static async Task InstallDefaultRouteWithNetshAsync(uint tunnelInterface, CancellationToken token)
    {
        var command =
            $"Set-NetIPInterface -InterfaceIndex {tunnelInterface} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 1 -IgnoreDefaultRoutes Disabled -ErrorAction Stop; " +
            $"& netsh.exe interface ipv4 delete route prefix=0.0.0.0/0 interface={tunnelInterface} store=active 2>$null | Out-Null; " +
            $"& netsh.exe interface ipv4 add route prefix=0.0.0.0/0 interface={tunnelInterface} metric=1 publish=no validlifetime=infinite preferredlifetime=infinite store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }";
        await PowerShellAsync(command, token);
    }

'@

$startMarker = '    private async Task VerifyFullTunnelRoutesAsync(uint tunnelInterface, CancellationToken token)'
$endMarker = '    private async Task RemoveInstalledRoutesCoreAsync(CancellationToken token)'
$start = $text.IndexOf($startMarker, [StringComparison]::Ordinal)
$end = $text.IndexOf($endMarker, [StringComparison]::Ordinal)
if ($start -lt 0 -or $end -le $start) {
    throw 'VerifyFullTunnelRoutesAsync block markers were not found; source layout changed.'
}

$updated = $text.Substring(0, $start) + $replacement + $text.Substring($end)

$directory = Split-Path -Parent $OutputPath
if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
[IO.File]::WriteAllText($OutputPath, $updated, [Text.UTF8Encoding]::new($false))
