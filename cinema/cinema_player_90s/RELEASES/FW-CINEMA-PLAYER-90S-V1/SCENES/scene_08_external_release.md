# Scene 8: External Release

- frames: 1896-2087 (192 frames, 8.0s)
- key: `external_release`

## Narrative purpose
The object is exposed externally.

## Emotional function
Release, expansion, exposure.

## Incoming cognitive state
A polished internal object.

## Transformation
external_connectivity makes its single biggest jump in the film; radiating release lines emanate from the core; stereo-widened sweeping audio.

## Outgoing cognitive state
An externally-connected, released structure.

## Visual primitives
- Full-bleed radial background gradient (`genome.organism._background_array`)
- Node/edge particle graph (`genome.organism._node_layout`, deterministic per-scene seed)
- Central polygon core (sides scale with `central_geometry`, jitter scales inversely with `structural_stability`)
- Scene-specific accent motif: radiating release lines

## Motion primitives
- Node pulse (per-node sine oscillation)
- Core rotation + per-second jitter reseed
- Slow camera drift (`genome.organism._view_window`)

## Camera behavior
- camera_distance: 0.800 -> 0.678 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/release.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "EXTERNAL RELEASE" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.950 | 0.991 |
| signal_density | 0.700 | 0.456 |
| pathway_organization | 0.800 | 0.841 |
| evidence_intensity | 0.550 | 0.591 |
| memory_depth | 0.650 | 0.894 |
| external_connectivity | 0.900 | 0.778 |
| structural_stability | 0.800 | 0.841 |
| palette_t | 0.880 | 0.978 |
| camera_distance | 0.800 | 0.678 |
| cognitive_load | 0.350 | 0.187 |
| release_readiness | 1.000 | 0.919 |

