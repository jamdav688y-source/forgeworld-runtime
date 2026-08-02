# Known Limitations -- FW-CINEMA-PLAYER-90S-V1

## Environment

- Built entirely in a Linux cloud dev container. Windows-specific
  deliverables (`.cmd`, `.ps1`) are written to spec but **not executed or
  verified** -- see `LAUNCH/launcher_validation.md`. Only the Linux/macOS
  launcher has been actually run and confirmed working.
- No real Windows desktop, GPU, or battery to measure performance
  against -- see `EVIDENCE/performance_report.md`.

## Content

- The film is procedurally generated abstract motion graphics (a
  particle/node-graph "organism" reskinned per scene), not footage from a
  video-generation model, and not human-directed cinematography or sound
  design. See `REVIEWS/artistic_review.md` for the full, honest
  assessment.
- Narration was rejected (`NARRATION_REJECTED`, see
  `AUDIO/audio_provenance.json`) because no speech-synthesis tool was
  available in this environment and the project's own law against using
  narration to compensate for unclear visuals ruled out faking it.
- The visual vocabulary is narrow: one recurring motif (node cluster +
  gradient field), varied by color/density/a small per-scene accent
  shape, not nine visually distinct "sets."

## Alert engine

- Fully implemented and tested (17 synthetic tests, all passing --
  `tests/test_alerts.py`), including a real simulation run against this
  actual release (`ALERTS/alert_simulation_report.json`). It has not been
  exercised against a *real* production fault during this build (the
  full-resolution renders and encodes both completed cleanly on the
  first attempt) -- only the deliberate interruption test during
  renderer development (see `MANIFESTS/build_manifest.json`) and the
  explicitly-labeled simulated alert scenarios exercised the BLOCKING/
  ACTIVE_WARNING paths.
- Concurrent-alert races (e.g. two processes detecting the same issue at
  the exact same instant) are not specifically guarded against beyond
  Python's GIL serializing individual method calls within one process --
  this engine is not designed for multi-process concurrent access.

## Player

- Local Flask dev server (not a production WSGI server) -- appropriate
  for a single-operator local tool, not for exposing beyond
  `127.0.0.1`.
- "Open Release Folder" returns a path + directory listing rather than
  literally opening a desktop file manager window, since this container
  has no desktop environment to open one in. On a real desktop OS this
  could be upgraded to actually invoke the OS file manager.
- Render progress during a long render is written to `progress.json` but
  the player's "Resume Render" button runs the render synchronously
  within the HTTP request in this implementation -- for the full 2160-
  frame render (minutes), this will hold the request open rather than
  streaming live progress. Real-time progress display would need a
  background-thread + polling design (the mobile-research project earlier
  in this repo has a working pattern for this that could be reused).

## Rendering

- Disk-space checks (`InsufficientDiskSpaceError`) use a conservative
  size estimate and were not deliberately triggered during this build's
  actual renders (there was ample space) -- the code path exists and is
  straightforward but wasn't exercised under a real low-disk condition.
- Frame rendering is single-threaded/single-process; no multi-core
  parallelism was implemented despite this container having 4 vCPUs --
  a reasonable next optimization (see the recommended next mission).
