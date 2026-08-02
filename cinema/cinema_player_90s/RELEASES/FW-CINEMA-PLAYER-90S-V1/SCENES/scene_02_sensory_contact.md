# Scene 2: Sensory Contact

- frames: 192-431 (240 frames, 10.0s)
- key: `sensory_contact`

## Narrative purpose
The organism starts receiving external signals.

## Emotional function
Alertness, an influx of new but unprocessed information.

## Incoming cognitive state
A small dormant cluster.

## Transformation
Signal density rises sharply; short sensory blips (audio) and node count increase.

## Outgoing cognitive state
A denser, still loosely-organized cluster carrying many raw signals.

## Visual primitives
- Full-bleed radial background gradient (`genome.organism._background_array`)
- Node/edge particle graph (`genome.organism._node_layout`, deterministic per-scene seed)
- Central polygon core (sides scale with `central_geometry`, jitter scales inversely with `structural_stability`)
- Scene-specific accent motif: (none -- base organism only)

## Motion primitives
- Node pulse (per-node sine oscillation)
- Core rotation + per-second jitter reseed
- Slow camera drift (`genome.organism._view_window`)

## Camera behavior
- camera_distance: 0.750 -> 0.550 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/sensory_signals.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "SENSORY CONTACT" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.150 | 0.300 |
| signal_density | 0.200 | 0.750 |
| pathway_organization | 0.100 | 0.300 |
| evidence_intensity | 0.050 | 0.150 |
| memory_depth | 0.080 | 0.150 |
| external_connectivity | 0.050 | 0.100 |
| structural_stability | 0.200 | 0.300 |
| palette_t | 0.080 | 0.220 |
| camera_distance | 0.750 | 0.550 |
| cognitive_load | 0.150 | 0.450 |
| release_readiness | 0.000 | 0.020 |

