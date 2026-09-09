param(
    [Parameter(Mandatory = $true)]
    [string]$BuildScript
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$BuildScript = (Resolve-Path -LiteralPath $BuildScript).Path
$WorkingDirectory = (Get-Item -LiteralPath $BuildScript).DirectoryName
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $WorkingDirectory '..'))
$AssetsDirectory = Join-Path $ProjectRoot 'app\src\main\assets'

$variants = @(
    [pscustomobject]@{ Name = 'amd64'; Target = 'x86_64-unknown-linux-musl'; Asset = 'csqtt-linux-amd64' },
    [pscustomobject]@{ Name = 'arm64'; Target = 'aarch64-unknown-linux-musl'; Asset = 'csqtt-linux-arm64' },
    [pscustomobject]@{ Name = 'armv7'; Target = 'armv7-unknown-linux-musleabihf'; Asset = 'csqtt-linux-armv7' }
)
$runDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("csqtt-linux-build-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $AssetsDirectory -Force | Out-Null

try {
    $processes = foreach ($variant in $variants) {
        $stdout = Join-Path $runDirectory "$($variant.Name).stdout.log"
        $stderr = Join-Path $runDirectory "$($variant.Name).stderr.log"
        $command = "call `"$BuildScript`" --build-variant $($variant.Target) $($variant.Asset)"
        $process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', $command) -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        [pscustomobject]@{
            Variant = $variant
            Stdout = $stdout
            Stderr = $stderr
            Process = $process
        }
    }

    $failed = @()
    foreach ($entry in $processes) {
        $entry.Process.WaitForExit()
        $entry.Process.Refresh()
        $exitCode = [int]$entry.Process.ExitCode
        if ($exitCode -ne 0) {
            $failed += [pscustomobject]@{ Entry = $entry; ExitCode = $exitCode; Reason = 'process' }
            continue
        }

        # Do not rely on cmd.exe argument forwarding for the final asset name.
        # The worker target directory is deterministic, so collect the ELF here
        # with the canonical asset name used by deploy.sh/provenance checks.
        $targetDirectory = Join-Path $ProjectRoot ("build\csqtt-uring-linux-" + $entry.Variant.Asset)
        $source = Join-Path $targetDirectory (Join-Path $entry.Variant.Target 'release\csqtt')
        $destination = Join-Path $AssetsDirectory $entry.Variant.Asset
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            $failed += [pscustomobject]@{ Entry = $entry; ExitCode = 1; Reason = "missing output: $source" }
            continue
        }
        Copy-Item -LiteralPath $source -Destination $destination -Force
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or (Get-Item -LiteralPath $destination).Length -le 0) {
            $failed += [pscustomobject]@{ Entry = $entry; ExitCode = 1; Reason = "asset copy failed: $destination" }
        }
        else {
            Write-Host ("Collected {0}: {1} bytes" -f $entry.Variant.Asset, (Get-Item -LiteralPath $destination).Length)
        }
    }

    if ($failed.Count -gt 0) {
        foreach ($failure in $failed) {
            $entry = $failure.Entry
            [Console]::Error.WriteLine("Build $($entry.Variant.Name) failed: $($failure.Reason) (code $($failure.ExitCode))")
            if (Test-Path -LiteralPath $entry.Stdout) {
                Get-Content -LiteralPath $entry.Stdout -Tail 120
            }
            if (Test-Path -LiteralPath $entry.Stderr) {
                Get-Content -LiteralPath $entry.Stderr -Tail 120
            }
        }
        exit 1
    }
}
finally {
    Remove-Item -LiteralPath $runDirectory -Recurse -Force -ErrorAction SilentlyContinue
}