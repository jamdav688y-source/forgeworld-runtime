# ForgeWorld Omega -- physical proof on the Windows PC.
#   .\scripts\omega-proof.ps1 -Device "Windows 11 desktop, Ryzen 7, 32 GB (owner's PC)" [-Model qwen2.5:1.5b]
# Writes docs\omega\proofs\windows-<date>.proof.json (signed). Publishing it is your decision.
param([Parameter(Mandatory=$true)][string]$Device, [string[]]$Model = @())
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
Push-Location $Here
try {
    & $Py -m pip install --user --quiet cryptography pytest
    $out = "docs\omega\proofs\windows-$(Get-Date -Format yyyyMMdd-HHmm).proof.json"
    $a = @("-m", "omega.proof", "run", "--device", $Device, "--out", $out)
    foreach ($m in $Model) { $a += @("--ollama-model", $m) }
    & $Py @a
    $rc = $LASTEXITCODE
    & $Py -m omega.proof verify $out
    Write-Host "`nProof written to $out (exit $rc). Nothing was uploaded."
    exit $rc
} finally { Pop-Location }
