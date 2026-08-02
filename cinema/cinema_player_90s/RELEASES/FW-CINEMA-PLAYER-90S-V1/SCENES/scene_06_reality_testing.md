# Scene 6: Reality Testing

- frames: 1368-1631 (264 frames, 11.0s)
- key: `reality_testing`

## Narrative purpose
The constructed artifact is stress-tested against evidence.

## Emotional function
Scrutiny; a held breath.

## Incoming cognitive state
A newly constructed but unproven structure.

## Transformation
evidence_intensity spikes (this scene's peak); a sweeping scan-line motif crosses the frame; a clean confirming chord (validation stem).

## Outgoing cognitive state
A validated structure -- structural_stability makes its biggest single-scene jump here.

## Visual primitives
- Full-bleed radial background gradient (`genome.organism._background_array`)
- Node/edge particle graph (`genome.organism._node_layout`, deterministic per-scene seed)
- Central polygon core (sides scale with `central_geometry`, jitter scales inversely with `structural_stability`)
- Scene-specific accent motif: sweeping scan line

## Motion primitives
- Node pulse (per-node sine oscillation)
- Core rotation + per-second jitter reseed
- Slow camera drift (`genome.organism._view_window`)

## Camera behavior
- camera_distance: 0.400 -> 0.500 (drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)

## Audio behavior
- primary stem: `AUDIO/stems/validation.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)
- plus continuous `atmosphere` and `cognitive_pulse` stems throughout

## Typography
- Title "REALITY TESTING" fades in/out over the first/last 15% of the scene (`genome/typography.py`)

## Native compositions
- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space scene data via `genome.organism._view_window`, not cropped from one another

## Validation requirements
- Every frame in this range must be present and checksum-valid in the frame cache manifest
- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)

## Measured state at scene boundaries
| metric | start | end |
|---|---|---|
| organism_maturity | 0.720 | 0.850 |
| signal_density | 0.600 | 0.650 |
| pathway_organization | 0.600 | 0.750 |
| evidence_intensity | 0.900 | 0.700 |
| memory_depth | 0.450 | 0.550 |
| external_connectivity | 0.250 | 0.350 |
| structural_stability | 0.350 | 0.700 |
| palette_t | 0.620 | 0.740 |
| camera_distance | 0.400 | 0.500 |
| cognitive_load | 0.850 | 0.600 |
| release_readiness | 0.550 | 0.800 |

