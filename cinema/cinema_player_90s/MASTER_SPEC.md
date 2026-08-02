# Master Specification -- FW-CINEMA-PLAYER-90S-V1

Machine-readable form: `MASTER_SPEC.json` (this file mirrors it for humans).

## Common (both masters)

| Property | Value |
|---|---|
| Frame rate | 24/1 constant (`r_frame_rate` and `avg_frame_rate` both `24/1`) |
| Duration | exactly 90.000 seconds |
| Decoded frame count | exactly 2,160 (verified by `ffprobe -count_frames`, not inferred from duration x fps) |
| Video codec | H.264 |
| Pixel format | yuv420p |
| Container | MP4 |
| Audio codec | AAC |
| Audio sample rate | 48,000 Hz |
| Audio channels | 2 (stereo) |

## 16:9 master

- Resolution: 1920x1080
- Output: `RELEASES/FW-CINEMA-PLAYER-90S-V1/MASTER/ForgeWorld_Cinema_Player_90s_1080p_24fps.mp4`

## 4:5 social master

- Resolution: 1080x1350 (native composition -- framed for this aspect
  ratio at render time, not center-cropped from the 16:9 master)
- Output: `RELEASES/FW-CINEMA-PLAYER-90S-V1/SOCIAL/ForgeWorld_Cinema_Player_90s_LinkedIn_4x5_24fps.mp4`

## Nine-scene chronology (frame-exact)

| # | Scene | Start (s) | End (s) | Frames |
|---|---|---|---|---|
| 1 | Latent Intelligence | 0 | 8 | 192 |
| 2 | Sensory Contact | 8 | 18 | 240 |
| 3 | Neural Convergence | 18 | 30 | 288 |
| 4 | Executive Competition | 30 | 41 | 264 |
| 5 | Coordinated Construction | 41 | 57 | 384 |
| 6 | Reality Testing | 57 | 68 | 264 |
| 7 | Cinematic Emergence | 68 | 79 | 264 |
| 8 | External Release | 79 | 87 | 192 |
| 9 | Recursive Learning | 87 | 90 | 72 |
| | **Total** | | | **2,160** |

## Content provenance (stated plainly, per the project's evidence laws)

This film's visuals are procedurally generated: a deterministic
particle/node system ("the organism") whose density, connectivity,
palette, and camera behavior evolve across the 2,160-frame timeline
according to values tracked in `CONTINUITY/cognitive_state_timeline.json`.
The audio is synthesized (layered tones/noise/envelopes), not recorded or
sourced from a sample library. Neither was produced by a video-generation
model, human cinematographer, or composer -- this is stated in
`REVIEWS/artistic_review.md` rather than described as more than it is.

## Environment disclaimer

Authored and rendered inside a Linux cloud dev container. Windows
desktop launch scripts (`LAUNCH/ForgeWorld_Cinema_Player.cmd`,
`LAUNCH/install_desktop_shortcut.ps1`) are written to standard Windows
scripting conventions but could not be executed or verified in this
environment -- see `LAUNCH/launcher_validation.md`.
