"""Deterministic render-plan compiler."""
from __future__ import annotations

from fractions import Fraction

from .project import validate_project


def compile_render_plan(project: dict, preview: bool = False) -> dict:
    validate_project(project)
    profile = project["profile"]
    scale = 2 if preview else 1
    width = max(2, (profile["width"] // scale) // 2 * 2)
    height = max(2, (profile["height"] // scale) // 2 * 2)
    rate = Fraction(profile["fps_num"], profile["fps_den"])
    frame_cursor = 0
    scenes = []
    for index, scene in enumerate(project["scenes"]):
        frames = max(1, round(scene["duration_ms"] * rate.numerator / (1000 * rate.denominator)))
        duration = Fraction(frames * rate.denominator, rate.numerator)
        scenes.append({
            "index": index,
            "scene_id": scene["scene_id"],
            "production_scene_id": scene["production_scene_id"],
            "asset_id": scene["asset_id"],
            "motion": scene.get("motion", "static"),
            "frame_start": frame_cursor,
            "frame_count": frames,
            "duration_num": duration.numerator,
            "duration_den": duration.denominator,
            "duration_seconds": f"{float(duration):.6f}",
            "source_in_ms": scene["source_in_ms"],
            "fit": scene["fit"],
            "label": scene["label"],
            "disclosures": list(scene["disclosures"]),
            "overlay_text": scene["overlay_text"],
            "captions": list(scene["captions"]),
        })
        frame_cursor += frames
    total = Fraction(frame_cursor * rate.denominator, rate.numerator)
    return {
        "schema_version": "forgeworld.video.render_plan.v1",
        "project_id": project["project_id"],
        "project_revision": project["revision"],
        "preview": bool(preview),
        "profile": {
            "width": width,
            "height": height,
            "fps_num": rate.numerator,
            "fps_den": rate.denominator,
            "fit": profile["fit"],
            "crf": min(35, profile["crf"] + 8) if preview else profile["crf"],
        },
        "scenes": scenes,
        "total_frames": frame_cursor,
        "total_duration_num": total.numerator,
        "total_duration_den": total.denominator,
        "total_duration_seconds": f"{float(total):.6f}",
        "audio": project["audio"],
        "lineage": project["lineage"],
    }
