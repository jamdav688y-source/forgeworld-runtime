"""Content-addressed receipt for local render outputs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .project import canonical_project_bytes, sha256_file


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_receipt(project: dict, plan: dict, output_path: Path, output_sha256: str, output_probe: dict,
                  tool_info: dict, mode: str, elapsed_seconds: float, receipt_path: Path,
                  captions_path: Path | None = None) -> dict:
    project_hash = hashlib.sha256(canonical_project_bytes(project)).hexdigest()
    plan_hash = hashlib.sha256(_canonical(plan)).hexdigest()
    media_id = "fwmedia-" + hashlib.sha256(f"{project_hash}:{plan_hash}:{output_sha256}".encode()).hexdigest()
    data = {
        "schema_version": "forgeworld.video.render_receipt.v1",
        "media_artifact_id": media_id,
        "project_id": project["project_id"],
        "project_revision": project["revision"],
        "project_sha256": project_hash,
        "render_plan_sha256": plan_hash,
        "package_lineage": project["lineage"],
        "input_assets": [{"asset_id": asset["asset_id"], "path": asset["path"], "sha256": asset["sha256"],
                          "kind": asset["kind"], "rights_status": asset["rights_status"]}
                         for asset in project["assets"]],
        "output": {"path": str(output_path), "sha256": output_sha256,
                   "duration": output_probe["format"].get("duration"),
                   "format_name": output_probe["format"].get("format_name"),
                   "video": {k: output_probe["video"].get(k) for k in ("codec_name", "width", "height", "r_frame_rate", "avg_frame_rate", "pix_fmt")},
                   "audio": ({k: output_probe["audio"].get(k) for k in ("codec_name", "sample_rate", "channels")} if output_probe.get("audio") else None)},
        "captions_sidecar": ({"path": str(output_path.with_suffix(".srt")), "sha256": sha256_file(captions_path)} if captions_path else None),
        "scene_lineage": [{"scene_id": scene["scene_id"], "production_scene_id": scene["production_scene_id"],
                           "label": scene["label"], "source_refs": scene["source_refs"], "citations": scene["citations"],
                           "disclosures": scene["disclosures"], "motion": scene.get("motion", "static")} for scene in project["scenes"]],
        "render": {"mode": mode, "elapsed_seconds": round(elapsed_seconds, 3), "toolchain": tool_info},
        "validation": {"ffprobe_passed": True, "project_hash_passed": True, "asset_hashes_passed": True},
        "publication_authorized": False,
        "upload_status": "NOT_ATTEMPTED",
        "evidence_status": "GENERATED_MEDIA_NOT_SOURCE_EVIDENCE",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_name(receipt_path.name + ".tmp")
    temporary.write_bytes(_canonical(data) + b"\n")
    # A temporary receipt must be on the same filesystem as its destination.
    os.replace(temporary, receipt_path)
    return data
