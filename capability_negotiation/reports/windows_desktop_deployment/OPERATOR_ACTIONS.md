# Operator Actions -- windows_desktop_deployment

Mission status: BLOCKED
Objective: Deploy, install, and validate the Cinema Player on an actual Windows desktop machine, including a working double-clickable desktop shortcut.
Generated: 2026-08-06T18:57:30Z

3 capability gap(s) must be resolved before this mission can proceed:

## 1. windows_filesystem_execution -- BLOCKED_BY_PLATFORM
- gap class: `missing_filesystem_access`
- evidence: platform.system()='Linux', required 'Windows'
- required operator action: This capability requires running on Windows -- it cannot be satisfied from the current platform. Execute the mission (or this specific step) on a real Windows machine.

## 2. windows_shell_execution -- BLOCKED_BY_PLATFORM
- gap class: `missing_filesystem_access`
- evidence: platform.system()='Linux', required 'Windows'
- required operator action: This capability requires running on Windows -- it cannot be satisfied from the current platform. Execute the mission (or this specific step) on a real Windows machine.

## 3. remote_desktop_access -- OPERATOR_REQUIRED
- gap class: `missing_operator_authorization`
- evidence: connector 'remote_desktop' unconfirmed: no live connector list supplied to this probe
- required operator action: Connect/authorize the 'remote_desktop' connector, or have the calling agent supply live connector evidence when negotiating this mission.

Resume condition: re-run negotiation for this mission after taking the actions above. Any requirement that was gapped and is now satisfied will be marked `DISCOVERED_AFTER_STARTUP` and the mission re-evaluated -- see check_resume().
