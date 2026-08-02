# Performance Report

## Environment measured (real, not the target device)

- CPU: Intel(R) Xeon(R) Processor @ 2.80GHz, 4 vCPUs (cloud container -- shared/virtualized, not representative of a dedicated desktop or the eventual Windows target machine)
- RAM: 15 GiB total, ~686 MiB used at measurement time
- GPU: none used -- all rendering is CPU-bound PIL/numpy; ffmpeg used libx264 (CPU) encoding, no hardware encoder invoked
- Disk: container-local overlay filesystem

## Render time (measured, this build)

| Stage | Frames | Resolution | Seconds | Frames/sec |
|---|---|---|---|---|
| 16:9 frame cache render | 2160 | 1920x1080 | 310.3 | 6.96 |
| 4:5 frame cache render | 2160 | 1080x1350 | 240.7 | 8.97 |

(4:5 is faster per-frame than 16:9 despite similar pixel count because
the background-gradient numpy computation and node-graph draw calls
scale with the frame's world-space view area, which differs slightly by
aspect ratio at the same camera_distance.)

## Encode time (measured, this build)

| Output | Preset | CRF | Seconds |
|---|---|---|---|
| 16:9 master | slow | 17 | 111.6 |
| 4:5 master | slow | 17 | 87.8 |
| 16:9 preview | veryfast | 23 | 52.6 |
| 4:5 preview | veryfast | 23 | 40.3 |

## Audio synthesis time (measured)

10 stems (90s stereo @ 48kHz each, 4,320,000 samples/channel) built via
vectorized numpy in 9.88 seconds total, including the mix/normalize step.

## Temporary vs. final storage

- Frame caches (`renderer/_frame_cache/`): ~634 MB (16:9) + ~557 MB
  (4:5) = ~1.19 GB. Not shipped in the release package (see
  `.gitignore` / `KNOWN_LIMITATIONS.md`) -- regenerable from code, kept
  locally only to support resumable rendering and re-encoding at a
  different quality without re-drawing frames.
- Final release media: 16:9 master ~19.5 MB, 4:5 master ~18.2 MB, plus
  two previews and audio stems -- full release package well under 100 MB.

## Interruptions and recoveries

One deliberate interruption was tested during development (see
`MANIFESTS/build_manifest.json` -- `interruption_recovery_test`): 30
deleted frames + 1 corrupted frame in a completed render, followed by a
resume call. Result: 31/2160 frames correctly identified as needing
re-render, 2129/2160 correctly skipped as already valid, 100% valid after
resume. No interruption occurred during the actual full-resolution
production renders documented above (both completed in a single pass).

## What this does NOT measure

Real-device (Windows desktop / laptop) performance, battery impact, GPU-
accelerated encoding, or behavior under memory pressure -- none of that
is available to measure from this container. Treat the numbers above as
"this specific cloud container, this one run," not as a general
performance guarantee.
