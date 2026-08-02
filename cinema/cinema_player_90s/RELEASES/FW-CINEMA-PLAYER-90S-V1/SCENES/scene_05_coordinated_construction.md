# Scene 5: Coordinated Construction

- frames: 984-1367 (384 frames, 16.0s)
- key: `coordinated_construction`

## Narrative purpose
The surviving mission is built out -- the film's longest scene (384 frames).

## Emotional function
Focused, productive effort.

## Incoming cognitive state
A single selected direction.

## Transformation
pathway_organization and structural_stability climb steadily; small rectilinear 'blueprint' accents appear; percussive construction audio.

## Outgoing cognitive state
A more stable, deliberately structured organism.

## Visual primitives
- Full-bleed radial background gradient (`genome.organism._background_array`)
- Node/edge particle graph (`genome.organism._node_layout`, deterministic per-scene seed)
- Central polygon core (sides scale with `central_geometry`, jitter scales inversely with `structural_stability`)
- Scene-specific accent motif: rectilinear blueprint marks

## Motion primitives
- Node pulse (per-node sine oscillation)
- Core rotation + per-second jitter reseed
- Slow camera drift (`genome.organism._view_window`)

## Camera behavior
- camera_distance: 0.450 -> 0.400 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/construction.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "COORDINATED CONSTRUCTION" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.550 | 0.720 |
| signal_density | 0.500 | 0.600 |
| pathway_organization | 0.650 | 0.600 |
| evidence_intensity | 0.450 | 0.900 |
| memory_depth | 0.350 | 0.450 |
| external_connectivity | 0.200 | 0.250 |
| structural_stability | 0.400 | 0.350 |
| palette_t | 0.500 | 0.620 |
| camera_distance | 0.450 | 0.400 |
| cognitive_load | 0.800 | 0.850 |
| release_readiness | 0.250 | 0.550 |

