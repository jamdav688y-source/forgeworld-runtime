# Release Summary -- FW-CINEMA-PLAYER-90S-V1

A 90-second, 24fps, procedurally-generated cinema piece with two native
masters (1920x1080 16:9, 1080x1350 4:5), nine causally-connected scenes
driven by a shared continuity model, ten synthesized audio stems, a
working cognitive alert engine, and a local Cinema Player application --
built from scratch in this cycle (no prior baseline existed; see
`baseline_preservation.md`).

## What's real and verified here

- Both masters ffprobe-verified: exactly 2,160 decoded frames, exactly
  90.000s, 24/1 constant frame rate, H.264/yuv420p/AAC 48kHz stereo
  (`VALIDATION/final_media_validation.md`).
- Continuity across all 8 scene transitions verified continuous, no
  metric out of range, visually confirmed via
  `REVIEWS/transition_contact_sheet.jpg`.
- Audio: 90.000s, 48kHz stereo, peak-normalized with no clipping, no
  unintended silence (`AUDIO/audio_validation.md`).
- Alert engine: 17 synthetic tests passing, plus a live simulation run
  against this actual release proving blocking alerts prevent
  `can_proceed_to_publish()` until resolved or dismissed
  (`ALERTS/alert_simulation_report.json`).
- Interrupted-render recovery deliberately tested and confirmed working
  (`MANIFESTS/build_manifest.json`).
- Local Cinema Player starts, serves both masters, and its Linux launch
  script was actually executed and confirmed working.

## What's honestly limited or unverified

See `known_limitations.md` for the full list. Headlines: this is
abstract procedural motion graphics, not directed cinema; narration was
rejected for lack of a synthesis tool; the Windows launcher is written
but untested (no Windows machine available in this environment).

## Where everything lives

- Masters: `MASTER/`, `SOCIAL/`
- Previews: `PREVIEW/`
- Audio: `AUDIO/` (stems + mix + provenance)
- Continuity evidence: `CONTINUITY/`
- Scene recipes: `SCENES/`
- Genome manifest: `GENOME/`
- Alert log + simulation: `ALERTS/`
- Validation reports: `VALIDATION/`
- Reviews (artistic/typography/contact sheets/waveform): `REVIEWS/`
- Launch scripts: `LAUNCH/`
- This evidence set: `EVIDENCE/`
- File integrity: `checksums.txt`

## Smallest operator action to watch it

See the Operator Action section of the final mission report, or
directly: run `LAUNCH/start_linux_macos.sh` (Linux/macOS, tested) or
`LAUNCH/ForgeWorld_Cinema_Player.cmd` (Windows, written but unverified),
then open http://127.0.0.1:5099 and press play.
