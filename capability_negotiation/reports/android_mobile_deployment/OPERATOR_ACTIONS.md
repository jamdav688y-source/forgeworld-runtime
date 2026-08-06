# Operator Actions -- android_mobile_deployment

Mission status: BLOCKED
Objective: Configure a new Android phone as a ForgeWorld mobile substrate: capture/index/retrieve local research, support Cinema review, and hand off mission packages to the Windows runtime -- without reproducing the full Windows ForgeWorld runtime on the phone.
Generated: 2026-08-06T19:12:16Z

4 capability gap(s) must be resolved before this mission can proceed:

## 1. android_filesystem_access -- UNAVAILABLE
- gap class: `missing_runtime`
- evidence: not running under Termux: TERMUX_VERSION unset, PREFIX='' (actual platform: Linux)
- required operator action: This capability requires running inside Termux on the actual Android device -- it cannot be satisfied from any other environment, including this one. Run negotiation from within Termux on the phone itself (`python3 capability_negotiation/negotiate.py ...` under Termux, once the repo is cloned there).

## 2. termux_shell_execution -- UNAVAILABLE
- gap class: `missing_runtime`
- evidence: not running under Termux: TERMUX_VERSION unset, PREFIX='' (actual platform: Linux)
- required operator action: This capability requires running inside Termux on the actual Android device -- it cannot be satisfied from any other environment, including this one. Run negotiation from within Termux on the phone itself (`python3 capability_negotiation/negotiate.py ...` under Termux, once the repo is cloned there).

## 3. camera_capture -- UNKNOWN
- gap class: `missing_dependency`
- evidence: static probe not possible; requires operator/runtime confirmation
- required operator action: Reachability of 'camera_capture' could not be conclusively determined (static probe not possible; requires operator/runtime confirmation); an operator should confirm it directly.

## 4. connector_authentication -- UNKNOWN
- gap class: `missing_dependency`
- evidence: static probe not possible; requires operator/runtime confirmation
- required operator action: Reachability of 'connector_authentication' could not be conclusively determined (static probe not possible; requires operator/runtime confirmation); an operator should confirm it directly.

Resume condition: re-run negotiation for this mission after taking the actions above. Any requirement that was gapped and is now satisfied will be marked `DISCOVERED_AFTER_STARTUP` and the mission re-evaluated -- see check_resume().
