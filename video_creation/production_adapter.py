"""Bridge an approved ForgeWorld production package to an explicit media map."""
from __future__ import annotations

import copy

from cognition import episode as episode_module, production as production_module

from .project import PROJECT_SCHEMA, ProjectError, validate_project


def project_from_package(package_builder, package_id: str, media_map: list[dict], assets: list[dict],
                         profile: dict, project_id: str, revision: int = 1, audio: dict | None = None) -> dict:
    """Build a render project from a validated package and explicit scene assets.

    Each media_map item requires scene_id, asset_id, duration_ms, source_in_ms,
    fit, and captions. Nothing in the package is treated as footage.
    """
    loaded = package_builder.load(package_id)
    package, manifest = loaded["package"], loaded["manifest"]
    if package.get("status") != production_module.DRAFT_PACKAGE or package.get("publication_authorized") is not False:
        raise ProjectError("production package is not a non-publishable draft")
    problems = production_module.validate_package(package)
    if problems:
        raise ProjectError("production package failed validation: " + ", ".join(problems))
    lineage = manifest.get("lineage", {})
    candidate_id = lineage.get("candidate_id")
    if not candidate_id or manifest.get("package_id") != package_id:
        raise ProjectError("package lineage is incomplete or mismatched")
    status = package_builder.studio.production_status(candidate_id)
    if status.get("status") != episode_module.APPROVED or status.get("publication_authorized") is not False:
        raise ProjectError("current candidate is not approved for production preparation")
    candidate = package_builder.exchange.get_record(candidate_id)
    if candidate is None or candidate.content_id != lineage.get("candidate_content_id"):
        raise ProjectError("candidate content identity does not match the package lineage")

    by_scene = {}
    for item in media_map:
        if not isinstance(item, dict) or set(item) != {"scene_id", "asset_id", "duration_ms", "source_in_ms", "fit", "captions"}:
            raise ProjectError("each media_map item must have exactly scene_id, asset_id, duration_ms, source_in_ms, fit, captions")
        if item["scene_id"] in by_scene:
            raise ProjectError("media_map contains a duplicate scene_id")
        by_scene[item["scene_id"]] = item

    scene_rows = []
    package_scenes = package["scenes"]
    if set(by_scene) != {scene["scene_id"] for scene in package_scenes}:
        raise ProjectError("media_map must map every production scene exactly once")
    for scene in package_scenes:
        media = by_scene[scene["scene_id"]]
        overlay = scene.get("on_screen_text") or ""
        # Keep production labels visible in the rendered frame; full disclosures
        # remain in the recipe and receipt even when too long for an overlay.
        scene_rows.append({
            "scene_id": scene["scene_id"],
            "production_scene_id": scene["scene_id"],
            "asset_id": media["asset_id"],
            "duration_ms": media["duration_ms"],
            "source_in_ms": media["source_in_ms"],
            "fit": media["fit"],
            "label": scene["label"],
            "source_refs": list(scene["source_refs"]),
            "citations": list(scene["citations"]),
            "disclosures": list(scene["disclosures"]),
            "overlay_text": overlay,
            "captions": copy.deepcopy(media["captions"]),
        })
    project = {
        "schema_version": PROJECT_SCHEMA,
        "project_id": project_id,
        "revision": revision,
        "asset_root": "assets",
        "profile": profile,
        "assets": assets,
        "scenes": scene_rows,
        "audio": audio,
        "lineage": {"package_id": package_id, "candidate_id": candidate_id,
                    "candidate_content_id": lineage["candidate_content_id"],
                    "package_version": manifest["package_version"], "publication_authorized": False},
    }
    return validate_project(project)
