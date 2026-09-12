param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$text = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8

# Keep the Wintun interface eligible for a real default route if the standard
# def1 (/1 + /1) form is removed by the local Windows networking stack.
$text = $text.Replace(
    'Set-NetIPInterface -InterfaceIndex {index} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 5 -ErrorAction Stop',
    'Set-NetIPInterface -InterfaceIndex {index} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 5 -IgnoreDefaultRoutes Disabled -ErrorAction Stop')

# Also clean a fallback /0 route left from an interrupted previous session.
$text = $text.Replace(
    '$wanted = @(''0.0.0.0/1'',''128.0.0.0/1''); ',
    '$wanted = @(''0.0.0.0/0'',''0.0.0.0/1'',''128.0.0.0/1''); ')

$replacement = @'
    private async Task VerifyFullTunnelRoutesAsync(uint tunnelInterface, CancellationToken token)
    {
        // Give Windows a separate-process observation window. On some Windows
        // systems New-NetRoute reports the /1 entries inside the creating CIM
        // session, but the networking stack removes them immediately afterwards.
        await Task.Delay(450, token);
        var lastOutput = await QueryFullTunnelRouteStateAsync(tunnelInterface, token);
        if (lastOutput.Contains("FULL_TUNNEL_OK", StringComparison.Ordinal))
        {
            Log?.Invoke($"[ROUTE] Split-default маршруты подтверждены на ifIndex {tunnelInterface}: {lastOutput}");
            return;
        }

        Log?.Invoke($"[ROUTE] PowerShell split-default исчез после создания ({lastOutput}); переключаемся на netsh/IP Helper путь");

        // netsh uses the native IP Helper route path instead of the NetTCPIP CIM
        // provider. This avoids machines where ActiveStore CIM routes briefly
        // appear and then vanish after the creating PowerShell process exits.
        for (var attempt = 1; attempt <= 3; attempt++)
        {
            await InstallSplitDefaultWithNetshAsync(tunnelInterface, token);
            await Task.Delay(400, token);
            lastOutput = await QueryFullTunnelRouteStateAsync(tunnelInterface, token);
            if (lastOutput.Contains("FULL_TUNNEL_OK", StringComparison.Ordinal))
            {
                Log?.Invoke($"[ROUTE] Split-default подтверждён через netsh на ifIndex {tunnelInterface}: {lastOutput}");
                return;
            }

            Log?.Invoke($"[ROUTE] netsh split-default не удержался ({lastOutput}), попытка {attempt}/3");
        }

        // Final fallback: keep the physical default route intact, but add a
        // lower-metric Wintun default. TURN/control and user «Напрямую» routes
        // are /32 or otherwise more specific, so they continue to bypass VPN.
        Log?.Invoke("[ROUTE] /1 маршруты удаляются Windows; резервный режим: 0.0.0.0/0 через Wintun");
        await InstallDefaultRouteWithNetshAsync(tunnelInterface, token);

        for (var attempt = 1; attempt <= 4; attempt++)
        {
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

            if (attempt < 4)
                await InstallDefaultRouteWithNetshAsync(tunnelInterface, token);
        }

        throw new InvalidOperationException(
            $"Windows не удержал full-tunnel маршруты VPNSL на ifIndex {tunnelInterface}. Диагностика: {lastOutput}");
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
            $"& netsh.exe interface ipv4 add route prefix=0.0.0.0/1 interface={tunnelInterface} nexthop=0.0.0.0 metric=5 publish=no validlifetime=infinite preferredlifetime=infinite store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; " +
            $"& netsh.exe interface ipv4 add route prefix=128.0.0.0/1 interface={tunnelInterface} nexthop=0.0.0.0 metric=5 publish=no validlifetime=infinite preferredlifetime=infinite store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }";
        await PowerShellAsync(command, token);
    }

    private static async Task InstallDefaultRouteWithNetshAsync(uint tunnelInterface, CancellationToken token)
    {
        var command =
            $"Set-NetIPInterface -InterfaceIndex {tunnelInterface} -AddressFamily IPv4 -AutomaticMetric Disabled -InterfaceMetric 1 -IgnoreDefaultRoutes Disabled -ErrorAction Stop; " +
            $"& netsh.exe interface ipv4 delete route prefix=0.0.0.0/0 interface={tunnelInterface} store=active 2>$null | Out-Null; " +
            $"& netsh.exe interface ipv4 add route prefix=0.0.0.0/0 interface={tunnelInterface} nexthop=0.0.0.0 metric=1 publish=no validlifetime=infinite preferredlifetime=infinite store=active | Out-Null; " +
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }";
        await PowerShellAsync(command, token);
    }

'@

$pattern = '(?s)    private async Task VerifyFullTunnelRoutesAsync\(uint tunnelInterface, CancellationToken token\)\s*\{.*?\n    \}\n\n(?=    private async Task RemoveInstalledRoutesCoreAsync)'
$updated = [regex]::Replace($text, $pattern, $replacement, 1)
if ($updated -eq $text) {
    throw 'VerifyFullTunnelRoutesAsync block was not replaced; source layout changed.'
}

$directory = Split-Path -Parent $OutputPath
if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
[IO.File]::WriteAllText($OutputPath, $updated, [Text.UTF8Encoding]::new($false))
