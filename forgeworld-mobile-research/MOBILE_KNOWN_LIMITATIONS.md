# Known Limitations -- FORGEWORLD-MOBILE-SUBSTRATE-001

## No Android device was reachable from this session (read this first)

This entire cycle was built in a Linux cloud dev container. Before
starting, this session checked its available connectors (`ListConnectors`)
and searched for any Android/Termux/ADB/device-bridge tool -- none
exists. The only phone-adjacent capability available is `PushNotification`,
a one-way notification channel with no shell, filesystem, or sensor
access. Given that, this cycle explicitly did **not**:

- Produce a real `MOBILE_DEVICE_PROFILE.json` with actual manufacturer,
  model, Android version, chipset, RAM, storage, or battery facts --
  `device_profile.py` is real, working discovery code that would produce
  one when run under Termux on an actual phone, but every field that
  depends on Termux/Android tooling honestly reports `null` with a
  `not_available_reason` when run here (`platform_class: "NOT_ANDROID"`,
  `device_classification: "UNKNOWN"`). See `test_device_profile.py`'s
  `test_build_profile_never_fabricates_android_facts_outside_termux`.
- Install or configure Termux itself.
- Test the "TAP -> ready" one-tap launch flow, or create a real Android
  home-screen shortcut.
- Capture a real screenshot from an actual phone screen/camera.
- Read real battery percentage, charging state, or thermal sensor data --
  `resource_guard.py`'s state machine is real and tested with synthetic
  values, but nothing here has ever seen an actual `termux-battery-status`
  reading.
- Validate anything about real mobile network behavior (offline/online
  transitions, cellular vs. wifi).

**What this means practically**: an operator running this on a real phone
under Termux should treat everything below as a checklist to verify, not
a guarantee. `capability_negotiation`'s `android_mobile_deployment`
mission negotiation (`MOBILE_CAPABILITY_STATE.json`) will look different
and mostly resolve to `AVAILABLE` once actually run inside Termux on the
device -- that's the intended behavior, not a bug in this report.

## What genuinely was built and validated (in this container)

- `screenshot_ingestion`, `local_research_index`, `cinema_review` --
  these are self-contained software capabilities that don't need a phone
  to be real; they were built, unit-tested, and exercised live through
  the actual Flask app and a real headless-browser click-through. See
  `MOBILE_VALIDATION_RESULTS.json`.
- `mission_handoff.py`'s capability bucketing logic is real and correctly
  reuses `capability_negotiation/engine.py` -- verified against actual
  probe evidence in this environment (e.g. `git`/`python` resolve
  `AVAILABLE`, `windows_shell_execution` resolves `BLOCKED_BY_PLATFORM`).
- `resource_guard.py`'s GREEN/YELLOW/ORANGE/RED thresholds are
  implemented and tested against synthetic metrics, but were **not
  tuned against real device behavior** -- an operator should watch actual
  battery/thermal drain on the real phone and adjust
  `LOW_BATTERY_PCT`/`HIGH_THERMAL_C`/etc. if they turn out to be wrong
  for that specific device.

## Scope deliberately not attempted this cycle

- No new SQLite tables were added for missions/cinema reviews -- both use
  simple JSON-file stores (`missions/`, `evidence/cinema_reviews/`)
  instead, to avoid migration risk to the existing, already-stabilized
  `screenshots.db` schema. Revisit if volume ever warrants a real table.
- No dedicated MISSIONS/CINEMA REVIEW/EVIDENCE tabs were built as
  separate top-level UI sections -- their functionality was folded into
  the existing Status tab via modals instead, per the mission's own
  "avoid complex dashboards" instruction (section 16). A dedicated
  Cinema Review approval workflow UI (swipe-to-approve, etc.) does not
  exist.
- No push-notification wiring for mission completion/failure -- NOTIFY
  role is unimplemented (see MOBILE_CINEMA_HANDOFF_SPEC.md).
- No semantic search integration for the "particle-level knowledge model"
  (section 11) -- `embeddings.py` remains the pre-existing disabled stub;
  this cycle didn't touch it.
- Connector policy (section 12): `connector_authentication` is registered
  as a `manual` check (always resolves `UNKNOWN`/operator-confirmation-
  required) by design, matching the project's existing rule that
  connector auth is never blanket-authorized by a mobile login.

## Pre-existing limitations (inherited, not introduced this cycle)

See the original `KNOWN_LIMITATIONS.md` for OCR/classification/semantic-
search caveats that predate this mission and are unchanged by it.
