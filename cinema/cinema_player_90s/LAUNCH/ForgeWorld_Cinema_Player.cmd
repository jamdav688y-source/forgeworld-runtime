@echo off
REM ForgeWorld Cinema Player launcher (Windows).
REM
REM WRITTEN TO STANDARD WINDOWS BATCH CONVENTIONS BUT NOT EXECUTED OR
REM VERIFIED IN THIS ENVIRONMENT -- this was authored in a Linux cloud
REM container with no Windows machine available to run it on. See
REM launcher_validation.md before relying on this. Please report back
REM (or fix and PR) any issue you hit running it on a real Windows box.
REM
REM Resolves paths relative to this script's own location (%~dp0) rather
REM than the caller's current directory, so it works regardless of where
REM it's double-clicked from or how the desktop shortcut invokes it.
REM Requires no administrator rights.

setlocal
set "SCRIPT_DIR=%~dp0"
set "CINEMA_ROOT=%SCRIPT_DIR%.."
set "PLAYER_APP=%CINEMA_ROOT%\player\app.py"

if not exist "%PLAYER_APP%" (
    echo [ForgeWorld Cinema Player] ERROR: could not find %PLAYER_APP%
    echo This launcher expects to live at ^<release^>\LAUNCH\ForgeWorld_Cinema_Player.cmd
    pause
    exit /b 1
)

REM Prefer the Python launcher (py), fall back to python on PATH.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYCMD=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYCMD=python"
    ) else (
        echo [ForgeWorld Cinema Player] ERROR: no Python interpreter found on PATH.
        echo Install Python 3 from https://python.org and try again.
        pause
        exit /b 1
    )
)

echo [ForgeWorld Cinema Player] Starting local player at http://127.0.0.1:5099 ...
echo [ForgeWorld Cinema Player] Close this window to stop the player.

cd /d "%CINEMA_ROOT%"
%PYCMD% -m pip install --quiet flask >nul 2>nul

start "" http://127.0.0.1:5099
%PYCMD% "%PLAYER_APP%"

if %ERRORLEVEL% NEQ 0 (
    echo [ForgeWorld Cinema Player] The player exited with an error ^(code %ERRORLEVEL%^).
    pause
)

endlocal
