# Launcher Validation

## start_linux_macos.sh -- TESTED, PASS

Actually executed in this build environment (Linux cloud container):

```
$ LAUNCH/start_linux_macos.sh &
[ForgeWorld Cinema Player] Starting local player at http://127.0.0.1:5099 ...
 * Running on http://127.0.0.1:5099
$ curl -s http://127.0.0.1:5099/api/status
200 OK, {...}
```

Confirms: script resolves its own path correctly regardless of caller's
CWD, finds `player/app.py`, starts the Flask process, the process binds
to `127.0.0.1:5099` and serves `/api/status`. This is the one launch path
with real evidence behind it.

## ForgeWorld_Cinema_Player.cmd -- WRITTEN, NOT TESTED

Authored to standard Windows batch conventions: `%~dp0`-relative path
resolution, `where`-based Python discovery (`py -3` preferred, `python`
fallback), a clear error message and `pause` if Python isn't found, opens
the default browser to the player URL, then runs the player in the
foreground so closing the window stops the server.

**This has not been run.** This session is a Linux cloud container with
no Windows machine available -- there is no way to execute a `.cmd` file
here to confirm it actually works. Known risks that can't be checked from
here: whether `py`/`python` resolve as expected on a given user's PATH,
whether `pip install flask` succeeds silently or needs a visible
progress indicator, and whether Windows Defender / SmartScreen flags an
unsigned batch file on first run (expected, not a bug, but worth telling
the operator to expect).

## install_desktop_shortcut.ps1 -- WRITTEN, NOT TESTED

Authored using the standard `WScript.Shell` COM `CreateShortcut` pattern
that's been stable across PowerShell versions for creating `.lnk` files,
targets the current user's Desktop folder only (no admin rights needed),
and points the shortcut at `ForgeWorld_Cinema_Player.cmd`.

**This has not been run**, for the same reason as above. Unverified:
whether `[Environment]::GetFolderPath("Desktop")` resolves correctly on
OneDrive-redirected Desktop folders (a common enterprise Windows
configuration), and whether the shortcut's relative `IconLocation`
resolves visually as expected.

## Recommendation

Before relying on the Windows path, an operator on an actual Windows
machine should:
1. Run `ForgeWorld_Cinema_Player.cmd` directly (double-click) and confirm
   the browser opens to a working player.
2. Run `install_desktop_shortcut.ps1` and confirm the desktop shortcut
   appears and launches the player.
3. Report back (or fix and contribute back) anything that doesn't match
   this document -- treat this file as a checklist to falsify, not a
   guarantee.
