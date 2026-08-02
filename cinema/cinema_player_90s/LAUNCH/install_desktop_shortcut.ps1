# ForgeWorld Cinema Player -- desktop shortcut installer (Windows PowerShell).
#
# WRITTEN TO STANDARD POWERSHELL/COM CONVENTIONS BUT NOT EXECUTED OR
# VERIFIED IN THIS ENVIRONMENT -- authored in a Linux cloud container
# with no Windows machine to run it on. See launcher_validation.md.
#
# Requires no administrator rights (creates the shortcut only in the
# current user's Desktop folder). Run with:
#   powershell -ExecutionPolicy Bypass -File install_desktop_shortcut.ps1

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cinemaRoot = Resolve-Path (Join-Path $scriptDir "..")
$targetCmd = Join-Path $scriptDir "ForgeWorld_Cinema_Player.cmd"

if (-not (Test-Path $targetCmd)) {
    Write-Error "Could not find $targetCmd -- run this script from inside the release's LAUNCH\ folder."
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "ForgeWorld Cinema Player.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetCmd
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = "ForgeWorld Cinema Player -- local 90-second cinema player"
$shortcut.IconLocation = "shell32.dll,41"  # generic media/film-reel-adjacent system icon; no custom .ico shipped
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath"
Write-Host "Double-click it to launch the ForgeWorld Cinema Player."
