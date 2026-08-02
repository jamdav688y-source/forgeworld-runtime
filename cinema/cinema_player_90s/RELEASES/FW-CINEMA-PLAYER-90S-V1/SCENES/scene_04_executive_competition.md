# Scene 4: Executive Competition

- frames: 720-983 (264 frames, 11.0s)
- key: `executive_competition`

## Narrative purpose
Candidate 'missions' compete for selection -- a rhythmic, decisive motif.

## Emotional function
Tension and selection pressure.

## Incoming cognitive state
An organized but undifferentiated network.

## Transformation
cognitive_load peaks; a rhythmic musical motif (executive_selection stem) marks discrete choices.

## Outgoing cognitive state
A network with one dominant, surviving direction.

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
- camera_distance: 0.600 -> 0.450 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/executive_selection.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "EXECUTIVE COMPETITION" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.450 | 0.550 |
| signal_density | 0.550 | 0.500 |
| pathway_organization | 0.550 | 0.650 |
| evidence_intensity | 0.350 | 0.450 |
| memory_depth | 0.250 | 0.350 |
| external_connectivity | 0.150 | 0.200 |
| structural_stability | 0.350 | 0.400 |
| palette_t | 0.380 | 0.500 |
| camera_distance | 0.600 | 0.450 |
| cognitive_load | 0.700 | 0.800 |
| release_readiness | 0.100 | 0.250 |

