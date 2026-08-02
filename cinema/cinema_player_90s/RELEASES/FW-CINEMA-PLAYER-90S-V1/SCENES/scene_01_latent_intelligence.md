# Scene 1: Latent Intelligence

- frames: 0-191 (192 frames, 8.0s)
- key: `latent_intelligence`

## Narrative purpose
Establish the organism before it has any external contact -- a small, sparse signal cluster in a near-black field.

## Emotional function
Dormant potential; quiet, not empty.

## Incoming cognitive state
None -- this is the film's starting state.

## Transformation
A few faint nodes appear and begin to pulse.

## Outgoing cognitive state
A small, loosely-connected cluster, ready to receive its first signal.

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
- camera_distance: 0.850 -> 0.750 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/atmosphere.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "LATENT INTELLIGENCE" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.050 | 0.150 |
| signal_density | 0.100 | 0.200 |
| pathway_organization | 0.050 | 0.100 |
| evidence_intensity | 0.000 | 0.050 |
| memory_depth | 0.050 | 0.080 |
| external_connectivity | 0.000 | 0.050 |
| structural_stability | 0.200 | 0.200 |
| palette_t | 0.000 | 0.080 |
| camera_distance | 0.850 | 0.750 |
| cognitive_load | 0.050 | 0.150 |
| release_readiness | 0.000 | 0.000 |

