# ForgeWorld Omega -- non-destructive install + verification on Windows.
#
#   powershell -ExecutionPolicy Bypass -File windows-verify.ps1 [-ExpectedCommit <sha>] [-ExistingRepo C:\path\to\forgeworld] [-Model qwen2.5:1.5b]
#
# Reads (never writes) an existing ForgeWorld checkout if given. Everything new
# goes to %USERPROFILE%\omega-verify, including a private venv.
# Rollback: Remove-Item -Recurse -Force "$env:USERPROFILE\omega-verify"
param([string]$ExpectedCommit = "", [string]$ExistingRepo = "", [string[]]$Model = @())
$ErrorActionPreference = "Continue"
$Base   = Join-Path $env:USERPROFILE "omega-verify"
$Url    = "https://github.com/jamdav688y-source/forgeworld-runtime.git"
$Branch = "ccr-0aad6294-t51qv4"
function Say($t) { Write-Host "`n== $t" }

Say "1. Environment"
Write-Host ("windows: " + [System.Environment]::OSVersion.VersionString)
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
$missing = @()
if (-not $py) { $missing += "Python 3.9+ (winget install Python.Python.3.12)" } else { & $py -V }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { $missing += "Git (winget install Git.Git)" } else { git --version }
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollama) { ollama --version } else { Write-Host "ollama: not installed (optional; model checks will be skipped)" }
if ($missing.Count -gt 0) { Write-Host "MISSING: $($missing -join '; ')"; exit 2 }

if ($ExistingRepo) {
  Say "2. Existing ForgeWorld checkout (read-only)"
  git -C $ExistingRepo rev-parse --abbrev-ref HEAD
  git -C $ExistingRepo rev-parse HEAD
  $dirty = (git -C $ExistingRepo status --porcelain | Measure-Object).Count
  Write-Host "uncommitted entries: $dirty (left untouched)"
}

Say "3. Isolated checkout in $Base"
New-Item -ItemType Directory -Force -Path $Base | Out-Null
$repo = Join-Path $Base "forgeworld-runtime"
if (Test-Path (Join-Path $repo ".git")) {
  if (git -C $repo status --porcelain) { Write-Host "Local changes in $repo -- refusing to touch them."; exit 3 }
  git -C $repo fetch -q origin $Branch; if ($LASTEXITCODE -ne 0) { Write-Host "fetch failed"; exit 4 }
  git -C $repo checkout -q --detach FETCH_HEAD
} else {
  git clone -q --branch $Branch $Url $repo; if ($LASTEXITCODE -ne 0) { Write-Host "clone failed"; exit 4 }
}
$head = (git -C $repo rev-parse HEAD).Trim()
Write-Host "installed commit: $head"
if ($ExpectedCommit -and -not $head.StartsWith($ExpectedCommit)) { Write-Host "COMMIT MISMATCH: expected $ExpectedCommit"; exit 5 }

Say "4. Private venv"
$venv = Join-Path $Base "venv"
if (-not (Test-Path $venv)) { & $py -m venv $venv }
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install -q cryptography pytest
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed"; exit 6 }

Push-Location $repo
try {
  Say "5. Test suite (native Windows)"
  & $vpy -m pytest -q -p no:cacheprovider omega/tests 2>&1 | Select-Object -Last 3

  Say "6. Signed proof"
  $ev = Join-Path $Base "evidence"; New-Item -ItemType Directory -Force -Path $ev | Out-Null
  $out = Join-Path $ev ("windows-" + (Get-Date -Format yyyyMMdd-HHmm) + ".proof.json")
  $cs = Get-CimInstance Win32_ComputerSystem
  $args2 = @("-m", "omega.proof", "run", "--device", "$($cs.Manufacturer) $($cs.Model), $([math]::Round($cs.TotalPhysicalMemory/1GB)) GB (owner's PC)", "--out", $out)
  if ($ollama) { foreach ($m in $Model) { $args2 += @("--ollama-model", $m) } }
  & $vpy @args2
  $rc = $LASTEXITCODE
  & $vpy -m omega.proof verify $out
  Write-Host "`nproof file: $out   (exit $rc; nothing was uploaded)"
  exit $rc
} finally { Pop-Location }
