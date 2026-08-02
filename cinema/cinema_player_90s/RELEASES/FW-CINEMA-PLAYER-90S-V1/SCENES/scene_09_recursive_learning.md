# Scene 9: Recursive Learning

- frames: 2088-2159 (72 frames, 3.0s)
- key: `recursive_learning`

## Narrative purpose
The shortest scene (72 frames, 3s) -- outcome evidence returns and updates memory.

## Emotional function
Reflective closure, not a hard ending.

## Incoming cognitive state
A released, externally-connected structure.

## Transformation
memory_depth reaches its film maximum; an inward spiral motif with audio delay/echo (recursion stem) represents feedback folding back in.

## Outgoing cognitive state
A more mature organism than the film began with -- ready, implicitly, to begin again.

## Visual primitives
- Full-bleed radial background gradient (`genome.organism._background_array`)
- Node/edge particle graph (`genome.organism._node_layout`, deterministic per-scene seed)
- Central polygon core (sides scale with `central_geometry`, jitter scales inversely with `structural_stability`)
- Scene-specific accent motif: inward feedback spiral

## Motion primitives
- Node pulse (per-node sine oscillation)
- Core rotation + per-second jitter reseed
- Slow camera drift (`genome.organism._view_window`)

## Camera behavior
- camera_distance: 0.677 -> 0.650 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/recursion.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "RECURSIVE LEARNING" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.991 | 1.000 |
| signal_density | 0.455 | 0.400 |
| pathway_organization | 0.841 | 0.850 |
| evidence_intensity | 0.591 | 0.600 |
| memory_depth | 0.895 | 0.950 |
| external_connectivity | 0.777 | 0.750 |
| structural_stability | 0.841 | 0.850 |
| palette_t | 0.978 | 1.000 |
| camera_distance | 0.677 | 0.650 |
| cognitive_load | 0.187 | 0.150 |
| release_readiness | 0.918 | 0.900 |

