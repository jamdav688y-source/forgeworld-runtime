"""Versioned project contract and strict validation for local video renders."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

PROJECT_SCHEMA = "forgeworld.video.project.v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RIGHTS = {"USER_PROVIDED", "LICENSED", "PUBLIC_DOMAIN", "GENERATED_LOCAL"}


class ProjectError(ValueError):
    """The project or an input asset violates the rendering contract."""


def _keys(value: dict, expected: set[str], label: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing or extra:
        raise ProjectError(f"{label} keys invalid; missing={sorted(missing)}, extra={sorted(extra)}")


def _text(value: Any, label: str, maximum: int = 500) -> None:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ProjectError(f"{label} must be text of at most {maximum} characters")


def validate_project(project: dict) -> dict:
    """Validate project structure, references, timing and resource ceilings."""
    if not isinstance(project, dict):
        raise ProjectError("project must be an object")
    _keys(project, {"schema_version", "project_id", "revision", "asset_root", "profile", "assets", "scenes", "audio", "lineage"}, "project")
    if project["schema_version"] != PROJECT_SCHEMA:
        raise ProjectError("unsupported project schema_version")
    if not isinstance(project["project_id"], str) or not _ID.fullmatch(project["project_id"]):
        raise ProjectError("project_id is malformed")
    if type(project["revision"]) is not int or project["revision"] < 1:
        raise ProjectError("revision must be a positive integer")
    root = project["asset_root"]
    if not isinstance(root, str) or not root or Path(root).is_absolute() or ".." in Path(root).parts:
        raise ProjectError("asset_root must be a safe relative directory")

    profile = project["profile"]
    if not isinstance(profile, dict):
        raise ProjectError("profile must be an object")
    _keys(profile, {"width", "height", "fps_num", "fps_den", "fit", "crf"}, "profile")
    for key in ("width", "height"):
        if type(profile[key]) is not int or profile[key] < 2 or profile[key] > 1920 or profile[key] % 2:
            raise ProjectError(f"profile.{key} must be an even integer from 2 through 1920")
    if type(profile["fps_num"]) is not int or type(profile["fps_den"]) is not int or not (1 <= profile["fps_num"] <= 60 and 1 <= profile["fps_den"] <= 1001):
        raise ProjectError("frame rate must be a positive rational number no greater than 60 fps")
    if profile["fit"] not in {"contain", "cover"}:
        raise ProjectError("profile.fit must be contain or cover")
    if type(profile["crf"]) is not int or not 15 <= profile["crf"] <= 35:
        raise ProjectError("profile.crf must be an integer from 15 through 35")

    assets = project["assets"]
    if not isinstance(assets, list) or not assets or len(assets) > 128:
        raise ProjectError("assets must contain between 1 and 128 records")
    asset_ids: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ProjectError("each asset must be an object")
        _keys(asset, {"asset_id", "path", "sha256", "kind", "rights_status"}, "asset")
        aid, path, digest = asset["asset_id"], asset["path"], asset["sha256"]
        if not isinstance(aid, str) or not _ID.fullmatch(aid) or aid in asset_ids:
            raise ProjectError("asset_id is malformed or duplicated")
        asset_ids.add(aid)
        rel = Path(path) if isinstance(path, str) else None
        if rel is None or rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ProjectError(f"asset {aid} path must be relative to asset_root")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ProjectError(f"asset {aid} sha256 is malformed")
        if asset["kind"] not in {"image", "video", "audio"}:
            raise ProjectError(f"asset {aid} has unsupported kind")
        if asset["rights_status"] not in _RIGHTS:
            raise ProjectError(f"asset {aid} has invalid rights_status")

    scenes = project["scenes"]
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 64:
        raise ProjectError("scenes must contain between 1 and 64 records")
    scene_ids: set[str] = set()
    total_ms = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ProjectError("each scene must be an object")
        _keys(scene, {"scene_id", "production_scene_id", "asset_id", "duration_ms", "source_in_ms", "fit", "label", "source_refs", "citations", "disclosures", "overlay_text", "captions"}, "scene")
        sid = scene["scene_id"]
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in scene_ids:
            raise ProjectError("scene_id is malformed or duplicated")
        scene_ids.add(sid)
        if scene["production_scene_id"] is not None and (not isinstance(scene["production_scene_id"], str) or not _ID.fullmatch(scene["production_scene_id"])):
            raise ProjectError(f"scene {sid} production_scene_id is malformed")
        if scene["asset_id"] not in asset_ids:
            raise ProjectError(f"scene {sid} refers to unknown asset_id")
        asset = next(a for a in assets if a["asset_id"] == scene["asset_id"])
        if asset["kind"] == "audio":
            raise ProjectError(f"scene {sid} cannot use an audio-only asset")
        duration = scene["duration_ms"]
        source_in = scene["source_in_ms"]
        if type(duration) is not int or not 250 <= duration <= 180_000:
            raise ProjectError(f"scene {sid} duration_ms must be 250..180000")
        if type(source_in) is not int or source_in < 0:
            raise ProjectError(f"scene {sid} source_in_ms must be a nonnegative integer")
        total_ms += duration
        if scene["fit"] not in {"contain", "cover"}:
            raise ProjectError(f"scene {sid} fit must be contain or cover")
        if scene["label"] not in {"QUOTED_SOURCE", "INTERPRETATION", "HYPOTHESIS", "DRAMATIZATION", "USER_AUTHORED"}:
            raise ProjectError(f"scene {sid} has an invalid epistemic label")
        for key in ("source_refs", "citations"):
            if not isinstance(scene[key], list) or any(not isinstance(item, str) or len(item) > 1000 for item in scene[key]):
                raise ProjectError(f"scene {sid} {key} must be a list of text references")
        _text(scene["overlay_text"], f"scene {sid} overlay_text", 500)
        if not isinstance(scene["disclosures"], list) or any(not isinstance(x, str) or len(x) > 500 for x in scene["disclosures"]):
            raise ProjectError(f"scene {sid} disclosures must be a list of short strings")
        captions = scene["captions"]
        if not isinstance(captions, list) or len(captions) > 100:
            raise ProjectError(f"scene {sid} captions must be a list with at most 100 cues")
        for cue in captions:
            if not isinstance(cue, dict):
                raise ProjectError(f"scene {sid} caption cue must be an object")
            _keys(cue, {"start_ms", "end_ms", "text"}, "caption")
            if type(cue["start_ms"]) is not int or type(cue["end_ms"]) is not int or not (0 <= cue["start_ms"] < cue["end_ms"] <= duration):
                raise ProjectError(f"scene {sid} caption timing must be within its scene")
            _text(cue["text"], f"scene {sid} caption text", 500)
    if total_ms > 180_000:
        raise ProjectError("project duration exceeds the 180-second v1 limit")

    audio = project["audio"]
    if audio is not None:
        if not isinstance(audio, dict):
            raise ProjectError("audio must be null or an object")
        _keys(audio, {"asset_id", "gain", "fade_out_ms"}, "audio")
        match = next((a for a in assets if a["asset_id"] == audio["asset_id"]), None)
        if match is None or match["kind"] != "audio":
            raise ProjectError("audio.asset_id must refer to an audio asset")
        if isinstance(audio["gain"], bool) or not isinstance(audio["gain"], (int, float)) or not math.isfinite(audio["gain"]) or not 0 <= audio["gain"] <= 2:
            raise ProjectError("audio.gain must be from 0 through 2")
        if type(audio["fade_out_ms"]) is not int or not 0 <= audio["fade_out_ms"] <= total_ms:
            raise ProjectError("audio.fade_out_ms is outside project duration")

    lineage = project["lineage"]
    if not isinstance(lineage, dict):
        raise ProjectError("lineage must be an object")
    _keys(lineage, {"package_id", "candidate_id", "candidate_content_id", "package_version", "publication_authorized"}, "lineage")
    if lineage["publication_authorized"] is not False:
        raise ProjectError("rendering must never authorize publication")
    for key in ("package_id", "candidate_id", "candidate_content_id"):
        if lineage[key] is not None and not isinstance(lineage[key], str):
            raise ProjectError(f"lineage.{key} must be text or null")
    if lineage["package_version"] is not None and (type(lineage["package_version"]) is not int or lineage["package_version"] < 1):
        raise ProjectError("lineage.package_version must be a positive integer or null")
    return project


def canonical_project_bytes(project: dict) -> bytes:
    validate_project(project)
    return json.dumps(project, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_project(path: Path, project: dict, overwrite: bool = False) -> Path:
    """Persist a validated project with an atomic replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ProjectError(f"project file already exists: {path}")
    data = canonical_project_bytes(project) + b"\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        if path.exists() and not overwrite:
            raise ProjectError(f"project file already exists: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_assets(project: dict, project_dir: Path) -> dict[str, Path]:
    """Resolve pinned assets under the declared asset root and verify hashes."""
    validate_project(project)
    project_root = Path(project_dir).resolve()
    base = (project_root / project["asset_root"]).resolve()
    try:
        base.relative_to(project_root)
    except ValueError:
        raise ProjectError("asset_root escapes the project directory") from None
    result: dict[str, Path] = {}
    for asset in project["assets"]:
        resolved = (base / asset["path"]).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            raise ProjectError(f"asset {asset['asset_id']} escapes the asset root") from None
        if not resolved.is_file():
            raise ProjectError(f"asset {asset['asset_id']} is missing")
        actual = sha256_file(resolved)
        if actual != asset["sha256"]:
            raise ProjectError(f"asset {asset['asset_id']} hash changed; create a new project revision")
        result[asset["asset_id"]] = resolved
    return result
