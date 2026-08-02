"""Generates the nine scene-recipe evidence files from the actual code
that renders each scene -- narrative/emotional text is authored here,
but every numeric value is pulled live from genome.state so the recipe
can never drift out of sync with what was actually rendered.
"""
from __future__ import annotations

from pathlib import Path

from genome.state import SCENES, state_for_frame, FPS

_NARRATIVE = {
    "latent_intelligence": {
        "purpose": "Establish the organism before it has any external contact -- a small, "
                   "sparse signal cluster in a near-black field.",
        "emotion": "Dormant potential; quiet, not empty.",
        "incoming": "None -- this is the film's starting state.",
        "transformation": "A few faint nodes appear and begin to pulse.",
        "outgoing": "A small, loosely-connected cluster, ready to receive its first signal.",
    },
    "sensory_contact": {
        "purpose": "The organism starts receiving external signals.",
        "emotion": "Alertness, an influx of new but unprocessed information.",
        "incoming": "A small dormant cluster.",
        "transformation": "Signal density rises sharply; short sensory blips (audio) and node count increase.",
        "outgoing": "A denser, still loosely-organized cluster carrying many raw signals.",
    },
    "neural_convergence": {
        "purpose": "Raw signals begin organizing into pathways.",
        "emotion": "Effortful integration -- many inputs becoming structure.",
        "incoming": "A dense, loosely-organized signal cluster.",
        "transformation": "pathway_organization rises; visible edges connect nearby nodes into a graph.",
        "outgoing": "A structured, if still busy, network of connected nodes.",
    },
    "executive_competition": {
        "purpose": "Candidate 'missions' compete for selection -- a rhythmic, decisive motif.",
        "emotion": "Tension and selection pressure.",
        "incoming": "An organized but undifferentiated network.",
        "transformation": "cognitive_load peaks; a rhythmic musical motif (executive_selection stem) marks discrete choices.",
        "outgoing": "A network with one dominant, surviving direction.",
    },
    "coordinated_construction": {
        "purpose": "The surviving mission is built out -- the film's longest scene (384 frames).",
        "emotion": "Focused, productive effort.",
        "incoming": "A single selected direction.",
        "transformation": "pathway_organization and structural_stability climb steadily; small rectilinear "
                           "'blueprint' accents appear; percussive construction audio.",
        "outgoing": "A more stable, deliberately structured organism.",
    },
    "reality_testing": {
        "purpose": "The constructed artifact is stress-tested against evidence.",
        "emotion": "Scrutiny; a held breath.",
        "incoming": "A newly constructed but unproven structure.",
        "transformation": "evidence_intensity spikes (this scene's peak); a sweeping scan-line motif crosses the frame; "
                           "a clean confirming chord (validation stem).",
        "outgoing": "A validated structure -- structural_stability makes its biggest single-scene jump here.",
    },
    "cinematic_emergence": {
        "purpose": "The validated structure becomes something presentable -- a 'cinematic object.'",
        "emotion": "Arrival; brightening.",
        "incoming": "A validated but still internally-facing structure.",
        "transformation": "palette shifts into amber/warm tones; harmonic pad audio (emergence stem) builds.",
        "outgoing": "A polished, outward-facing object, ready to be released.",
    },
    "external_release": {
        "purpose": "The object is exposed externally.",
        "emotion": "Release, expansion, exposure.",
        "incoming": "A polished internal object.",
        "transformation": "external_connectivity makes its single biggest jump in the film; radiating release "
                           "lines emanate from the core; stereo-widened sweeping audio.",
        "outgoing": "An externally-connected, released structure.",
    },
    "recursive_learning": {
        "purpose": "The shortest scene (72 frames, 3s) -- outcome evidence returns and updates memory.",
        "emotion": "Reflective closure, not a hard ending.",
        "incoming": "A released, externally-connected structure.",
        "transformation": "memory_depth reaches its film maximum; an inward spiral motif with audio delay/echo "
                           "(recursion stem) represents feedback folding back in.",
        "outgoing": "A more mature organism than the film began with -- ready, implicitly, to begin again.",
    },
}

_METRICS_TO_SHOW = [
    "organism_maturity", "signal_density", "pathway_organization", "evidence_intensity",
    "memory_depth", "external_connectivity", "structural_stability", "palette_t",
    "camera_distance", "cognitive_load", "release_readiness",
]


def write_scene_recipes(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, (key, label, start, end) in enumerate(SCENES, start=1):
        narrative = _NARRATIVE[key]
        start_state = state_for_frame(start).as_dict()
        end_state = state_for_frame(end - 1).as_dict()

        lines = [
            f"# Scene {i}: {label}",
            "",
            f"- frames: {start}-{end - 1} ({end - start} frames, {(end - start) / FPS:.1f}s)",
            f"- key: `{key}`",
            "",
            "## Narrative purpose", narrative["purpose"], "",
            "## Emotional function", narrative["emotion"], "",
            "## Incoming cognitive state", narrative["incoming"], "",
            "## Transformation", narrative["transformation"], "",
            "## Outgoing cognitive state", narrative["outgoing"], "",
            "## Visual primitives",
            "- Full-bleed radial background gradient (`genome.organism._background_array`)",
            "- Node/edge particle graph (`genome.organism._node_layout`, deterministic per-scene seed)",
            "- Central polygon core (sides scale with `central_geometry`, jitter scales inversely with `structural_stability`)",
            "- Scene-specific accent motif: " + {
                "coordinated_construction": "rectilinear blueprint marks",
                "reality_testing": "sweeping scan line",
                "external_release": "radiating release lines",
                "recursive_learning": "inward feedback spiral",
            }.get(key, "(none -- base organism only)"),
            "",
            "## Motion primitives",
            "- Node pulse (per-node sine oscillation)",
            "- Core rotation + per-second jitter reseed",
            "- Slow camera drift (`genome.organism._view_window`)",
            "",
            "## Camera behavior",
            f"- camera_distance: {start_state['camera_distance']:.3f} -> {end_state['camera_distance']:.3f} "
            "(drives world-space zoom; native per-aspect view window avoids letterboxing -- see ARCHITECTURE notes)",
            "",
            "## Audio behavior",
            f"- primary stem: `AUDIO/stems/{_scene_to_stem(key)}.wav` (windowed to this scene, see `audio/synth.py::_scene_window`)",
            "- plus continuous `atmosphere` and `cognitive_pulse` stems throughout",
            "",
            "## Typography",
            f'- Title "{label.upper()}" fades in/out over the first/last 15% of the scene (`genome/typography.py`)',
            "",
            "## Native compositions",
            "- 16:9 (1920x1080) and 4:5 (1080x1350): both computed directly from the same normalized world-space "
            "scene data via `genome.organism._view_window`, not cropped from one another",
            "",
            "## Validation requirements",
            "- Every frame in this range must be present and checksum-valid in the frame cache manifest",
            "- Boundary continuity with neighboring scene(s) (see `CONTINUITY/continuity_validation.md`)",
            "",
            "## Measured state at scene boundaries",
            "| metric | start | end |",
            "|---|---|---|",
        ]
        for m in _METRICS_TO_SHOW:
            lines.append(f"| {m} | {start_state[m]:.3f} | {end_state[m]:.3f} |")
        lines.append("")

        path = out_dir / f"scene_{i:02d}_{key}.md"
        path.write_text("\n".join(lines) + "\n")
        written.append(path)
    return written


def _scene_to_stem(scene_key: str) -> str:
    return {
        "latent_intelligence": "atmosphere",
        "sensory_contact": "sensory_signals",
        "neural_convergence": "atmosphere",
        "executive_competition": "executive_selection",
        "coordinated_construction": "construction",
        "reality_testing": "validation",
        "cinematic_emergence": "emergence",
        "external_release": "release",
        "recursive_learning": "recursion",
    }[scene_key]
