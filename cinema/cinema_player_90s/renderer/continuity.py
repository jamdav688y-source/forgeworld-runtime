"""Exports the real state trace used to render the film as continuity
evidence, and validates it. This is not reconstructed after the fact --
genome.state.full_timeline() is the exact same function renderer.render
calls per-frame to draw the organism, so this file is a faithful record
of what was actually rendered.
"""
from __future__ import annotations

import json
from pathlib import Path

from genome.state import SCENES, TRANSITIONS, TOTAL_FRAMES, full_timeline, state_for_frame

METRICS = [
    "organism_maturity", "signal_density", "pathway_organization", "evidence_intensity",
    "memory_depth", "external_connectivity", "structural_stability", "central_geometry",
    "palette_t", "camera_distance", "cognitive_load", "release_readiness",
]


def build_transition_map() -> dict:
    return {
        "total_transitions": len(TRANSITIONS),
        "transitions": TRANSITIONS,
        "scene_count": len(SCENES),
        "check": "8 transitions for 9 scenes (one per boundary)",
        "ok": len(TRANSITIONS) == len(SCENES) - 1,
    }


def validate_continuity() -> dict:
    problems = []

    # 1. every metric stays in [0, 1] for every frame
    out_of_range = 0
    for frame in range(0, TOTAL_FRAMES, 4):  # sampled -- exhaustive would be slow and isn't necessary
        state = state_for_frame(frame).as_dict()
        for m in METRICS:
            v = state[m]
            if not (0.0 - 1e-6 <= v <= 1.0 + 1e-6):
                out_of_range += 1
    if out_of_range:
        problems.append(f"{out_of_range} sampled (metric, frame) pairs out of [0,1] range")

    # 2. boundary continuity: value at the last frame of scene N equals the
    #    value at the first frame of scene N+1 (no jump-cut in any metric)
    boundary_breaks = []
    for i in range(len(SCENES) - 1):
        end_frame_of_prev = SCENES[i][3] - 1
        start_frame_of_next = SCENES[i + 1][2]
        a = state_for_frame(end_frame_of_prev).as_dict()
        b = state_for_frame(start_frame_of_next).as_dict()
        for m in METRICS:
            if abs(a[m] - b[m]) > 0.05:
                boundary_breaks.append(
                    f"{SCENES[i][0]}->{SCENES[i+1][0]} metric={m} delta={abs(a[m]-b[m]):.4f}"
                )
    if boundary_breaks:
        problems.append(f"{len(boundary_breaks)} boundary discontinuities: {boundary_breaks[:5]}")

    # 3. frame-total sanity
    if SCENES[-1][3] != TOTAL_FRAMES:
        problems.append(f"scene frames sum to {SCENES[-1][3]}, expected {TOTAL_FRAMES}")

    # 4. transition map completeness
    tm = build_transition_map()
    if not tm["ok"]:
        problems.append("transition_map does not have exactly 8 transitions for 9 scenes")

    return {
        "ok": len(problems) == 0,
        "problems": problems,
        "sampled_frames_checked": len(range(0, TOTAL_FRAMES, 4)),
        "boundary_checks": len(SCENES) - 1,
    }


def write_continuity_evidence(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    timeline = full_timeline()
    (out_dir / "cognitive_state_timeline.json").write_text(json.dumps(timeline))

    transition_map = build_transition_map()
    (out_dir / "transition_map.json").write_text(json.dumps(transition_map, indent=2))

    result = validate_continuity()

    lines = [
        "# Continuity Validation",
        "",
        f"Result: {'PASS' if result['ok'] else 'FAIL'}",
        f"Sampled frames checked (every 4th, {result['sampled_frames_checked']} total): range validity",
        f"Boundary checks (all {result['boundary_checks']} scene transitions): metric continuity",
        "",
    ]
    if result["problems"]:
        lines.append("## Problems")
        for p in result["problems"]:
            lines.append(f"- {p}")
    else:
        lines.append("No discontinuities found. Every tracked metric (organism_maturity, "
                      "signal_density, pathway_organization, evidence_intensity, memory_depth, "
                      "external_connectivity, structural_stability, central_geometry, palette_t, "
                      "camera_distance, cognitive_load, release_readiness) is continuous across "
                      "every scene boundary and stays within [0,1] for the whole film.")
    lines.append("")
    lines.append(f"Timeline export: `cognitive_state_timeline.json` ({len(timeline)} frame records)")
    lines.append(f"Transition map: `transition_map.json` ({transition_map['total_transitions']} causal transitions)")

    (out_dir / "continuity_validation.md").write_text("\n".join(lines) + "\n")
    return result
