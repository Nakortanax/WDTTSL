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

$replacement = @'
    private async Task VerifyFullTunnelRoutesAsync(uint tunnelInterface, CancellationToken token)
    {
        // Observe the route table from a fresh PowerShell process. The affected
        // Windows hosts briefly report the /1 routes in the creating CIM process
        // and then remove them immediately afterwards.
        await Task.Delay(450, token);
        var lastOutput = await QueryFullTunnelRouteStateAsync(tunnelInterface, token);
        if (lastOutput.Contains("FULL_TUNNEL_OK", StringComparison.Ordinal))
        {
            Log?.Invoke($"[ROUTE] Split-default маршруты подтверждены на ifIndex {tunnelInterface}: {lastOutput}");
            return;
        }

        Log?.Invoke($"[ROUTE] PowerShell split-default исчез после создания ({lastOutput}); пробуем native netsh route");

        // netsh reaches the native IP Helper routing path instead of creating the
        // route through the NetTCPIP CIM provider. nexthop is intentionally
        // omitted: these are on-link routes through the Wintun interface.
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

        // Final fallback. Keep the physical default route in place, but install a
        // lower-cost Wintun default. TURN/control /32 routes and user «Напрямую»
        // prefixes remain more specific and therefore continue to use the
        // physical interface.
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
