# ForgeWorld Omega -- forge node (Windows / PowerShell).
# Usage:  .\scripts\omega-forge.ps1 setup [label]
#         .\scripts\omega-forge.ps1 <omega command> [args...]
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $env:OMEGA_HOME) { $env:OMEGA_HOME = Join-Path $env:USERPROFILE ".forgeworld-omega" }
$Py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
if ($args.Count -gt 0 -and $args[0] -eq "setup") {
    & $Py -m pip install --user cryptography pytest
    $label = if ($args.Count -gt 1) { $args[1] } else { "forge-pc" }
    if (-not (Test-Path (Join-Path $env:OMEGA_HOME "node.json"))) {
        & $Py -m omega --home $env:OMEGA_HOME init --label $label --profile forge
    }
    & $Py -m omega --home $env:OMEGA_HOME diag --probe-ollama
    exit $LASTEXITCODE
}
Push-Location $Here
try { & $Py -m omega @args; exit $LASTEXITCODE } finally { Pop-Location }
