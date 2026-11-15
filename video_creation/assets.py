"""Explicit local asset import and inspection helpers."""
from __future__ import annotations

import shutil
import os
import tempfile
from pathlib import Path

from .project import PROJECT_SCHEMA, ProjectError, sha256_file, validate_project, write_project
from .project import _ID

_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi"},
    "audio": {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"},
}


def infer_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    for kind, extensions in _EXTENSIONS.items():
        if suffix in extensions:
            return kind
    raise ProjectError(f"unsupported media extension: {suffix or '(none)'}")


def import_asset(source_path: Path, project_dir: Path, asset_id: str, rights_status: str) -> dict:
    """Copy an explicitly selected file into project assets and pin its hash."""
    if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
        raise ProjectError("asset_id is malformed")
    if rights_status not in {"USER_PROVIDED", "LICENSED", "PUBLIC_DOMAIN", "GENERATED_LOCAL"}:
        raise ProjectError("rights_status is invalid")
    source = Path(source_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ProjectError("selected asset is not a file")
    kind = infer_kind(source)
    asset_root = (Path(project_dir) / "assets").resolve()
    asset_root.mkdir(parents=True, exist_ok=True)
    destination = asset_root / f"{asset_id}{source.suffix.lower()}"
    try:
        destination.resolve().relative_to(asset_root)
    except ValueError:
        raise ProjectError("asset_id would escape the project asset directory") from None
    if destination.exists():
        raise ProjectError(f"asset already exists: {asset_id}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{asset_id}.", suffix=source.suffix.lower() + ".tmp", dir=asset_root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            with source.open("rb") as input_stream:
                shutil.copyfileobj(input_stream, output, length=1024 * 1024)
        if destination.exists():
            raise ProjectError(f"asset already exists: {asset_id}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "asset_id": asset_id,
        "path": destination.name,
        "sha256": sha256_file(destination),
        "kind": kind,
        "rights_status": rights_status,
    }


def create_quickstart_project(project_dir: Path, project_id: str, media_paths: list[Path],
                              duration_ms: int = 3000, width: int = 1080, height: int = 1920,
                              fit: str = "contain", rights_status: str = "USER_PROVIDED") -> dict:
    """Create a minimal local project from selected stills/videos and an optional audio file."""
    project_dir = Path(project_dir).expanduser().resolve()
    project_file = project_dir / "project.json"
    if project_file.exists():
        raise ProjectError(f"project already exists: {project_file}")
    if not media_paths or len(media_paths) > 65:
        raise ProjectError("select 1 to 64 image/video files and optionally one audio file")
    project_dir.mkdir(parents=True, exist_ok=True)
    imported: list[Path] = []
    assets = []
    scenes = []
    audio = None
    try:
        for index, selected in enumerate(media_paths, start=1):
            kind = infer_kind(Path(selected))
            if kind == "audio":
                if audio is not None:
                    raise ProjectError("quickstart supports one optional audio file")
                asset_id = "audio-001"
            else:
                asset_id = f"asset-{len(scenes) + 1:03d}"
            row = import_asset(Path(selected), project_dir, asset_id, rights_status)
            imported.append(project_dir / "assets" / row["path"])
            assets.append(row)
            if kind != "audio":
                scenes.append({"scene_id": f"scene-{len(scenes) + 1:03d}", "production_scene_id": None,
                               "asset_id": asset_id, "duration_ms": duration_ms, "source_in_ms": 0,
                               "fit": fit, "label": "USER_AUTHORED", "source_refs": [], "citations": [],
                               "disclosures": [], "overlay_text": "", "captions": []})
            else:
                audio = {"asset_id": asset_id, "gain": 0.7, "fade_out_ms": min(500, duration_ms * len(scenes))}
        if not scenes:
            raise ProjectError("quickstart needs at least one image or video file")
        project = {
            "schema_version": PROJECT_SCHEMA,
            "project_id": project_id,
            "revision": 1,
            "asset_root": "assets",
            "profile": {"width": width, "height": height, "fps_num": 30, "fps_den": 1,
                        "fit": fit, "crf": 23},
            "assets": assets,
            "scenes": scenes,
            "audio": audio,
            "lineage": {"package_id": None, "candidate_id": None, "candidate_content_id": None,
                        "package_version": None, "publication_authorized": False},
        }
        validate_project(project)
        write_project(project_file, project)
        return project
    except Exception:
        for path in imported:
            path.unlink(missing_ok=True)
        raise
