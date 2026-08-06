# Mobile Cinema Handoff Spec

How the phone supports the Cinema Engine without attempting heavy final
rendering locally, per mission section 10.

## AVAILABLE on mobile (implemented, tested)

All served by `cinema_review.py`, real integration with the actual
Cinema Player release at `cinema/cinema_player_90s/RELEASES/`:

- `discover_cinema_artifacts()` -- lists real masters/previews/contact
  sheets/reviews/validation reports from disk (10 real files found
  against the FW-CINEMA-PLAYER-90S-V1 release in this repo).
- `read_validation_summary(version)` -- surfaces the real ffprobe-backed
  validation result (`overall_pass`, per-master measured specs) for
  mobile review, not a re-derived or guessed value.
- `create_review()` / `save_review()` / `list_reviews()` /
  `review_queue_summary()` -- the review record schema from the mission
  spec, JSON-file-backed under `evidence/cinema_reviews/`, exposed via
  `GET/POST /api/cinema/reviews`.
- Never modifies the original artifact -- `save_review()` only ever
  writes to `evidence/cinema_reviews/`, confirmed by
  `test_defects_recorded_do_not_modify_original_artifact`.
- Comparing revisions / captions / mobile readability review: supported
  structurally via `review_type` (`revision_comparison`,
  `caption_review`, `mobile_readability` are valid values) -- no
  dedicated UI for side-by-side comparison was built this cycle (see
  MOBILE_KNOWN_LIMITATIONS.md).
- Watching finished media: the existing Cinema Player
  (`cinema/cinema_player_90s/player/app.py`) already serves both masters
  over HTTP with native `<video>` controls; a phone's mobile browser can
  reach it exactly like a desktop browser can, provided it's on the same
  network as wherever that player process is running. This mobile
  research app does not re-implement video playback itself.

## DELEGATE_TO_WINDOWS (never attempted locally, by mission-level policy)

Declared in `capability_negotiation/missions.py`'s
`android_mobile_deployment` mission, `delegate_to_windows_ids`:

- `desktop_shortcut_creation` -- genuinely Windows-platform-locked
  (`.cmd`/`.ps1`, `WScript.Shell` COM object); registered with a
  `platform: Windows` check, correctly reads `BLOCKED_BY_PLATFORM` from
  any non-Windows device.
- `cinema_render_1080p_24fps` -- delegated as a **mobile battery/thermal
  policy decision**, not a hard platform requirement. Important
  correction to the mission brief's own framing: the actual 1080p/24fps
  Cinema master in this repository was rendered successfully on a Linux
  container (this same session), not Windows -- see
  `cinema/cinema_player_90s/RELEASES/FW-CINEMA-PLAYER-90S-V1/VALIDATION/`.
  So the reason a phone shouldn't do this locally is "don't run
  multi-minute CPU-bound ffmpeg encodes on battery," not "this literally
  cannot run outside Windows." Registered as a `manual` check
  (operator/mission-level judgment call) rather than a `platform` check,
  because a `platform: Windows` check would have been factually wrong.

## How delegation actually reaches Windows

Via `mission_handoff.py`: `create_mission_package()` negotiates every
`required_capabilities` entry through `capability_negotiation/engine.py`
and buckets each into `mobile_available` / `windows_required` /
`operator_required`. A package with `cinema_render_1080p_24fps` in
`windows_required` is a complete, self-contained request -- see
`mission_handoff.py`'s own docstring and
`test_windows_never_reconstructs_request_from_conversation_history`.

## What was NOT built this cycle

- A dedicated "revision comparison" UI (side-by-side old vs. new frame
  diff) -- the schema supports it (`review_type: revision_comparison`)
  but no comparison view was implemented.
- Push notifications to the phone when a Windows-side render completes --
  the mission's NOTIFY role is not wired to any actual notification
  channel in this cycle (would need a real handoff-completion signal from
  the Windows side, which doesn't exist yet since no Windows execution
  was performed).
