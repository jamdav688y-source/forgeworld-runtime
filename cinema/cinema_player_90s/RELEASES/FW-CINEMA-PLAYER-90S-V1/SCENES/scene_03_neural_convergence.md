# Scene 3: Neural Convergence

- frames: 432-719 (288 frames, 12.0s)
- key: `neural_convergence`

## Narrative purpose
Raw signals begin organizing into pathways.

## Emotional function
Effortful integration -- many inputs becoming structure.

## Incoming cognitive state
A dense, loosely-organized signal cluster.

## Transformation
pathway_organization rises; visible edges connect nearby nodes into a graph.

## Outgoing cognitive state
A structured, if still busy, network of connected nodes.

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
- camera_distance: 0.550 -> 0.600 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/atmosphere.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "NEURAL CONVERGENCE" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.300 | 0.450 |
| signal_density | 0.750 | 0.550 |
| pathway_organization | 0.300 | 0.550 |
| evidence_intensity | 0.150 | 0.350 |
| memory_depth | 0.150 | 0.250 |
| external_connectivity | 0.100 | 0.150 |
| structural_stability | 0.300 | 0.350 |
| palette_t | 0.220 | 0.380 |
| camera_distance | 0.550 | 0.600 |
| cognitive_load | 0.450 | 0.700 |
| release_readiness | 0.020 | 0.100 |

