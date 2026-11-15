"""Command-line entry points for the local video capability."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assets import create_quickstart_project, import_asset
from .ffmpeg_backend import RenderError, doctor, probe, render_project
from .project import ProjectError, resolve_assets, validate_project


def _load(path: Path) -> dict:
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"could not read project JSON: {exc}") from None
    return validate_project(project)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forgeworld-video", description="Local ForgeWorld video renderer")
    parser.add_argument("--version", action="version", version="ForgeWorld Local Video Renderer 1.0")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="inspect local FFmpeg capabilities")
    quick = sub.add_parser("quickstart", help="create a local project from selected media files")
    quick.add_argument("project_dir", type=Path)
    quick.add_argument("--project-id", required=True)
    quick.add_argument("--media", action="append", required=True, type=Path)
    quick.add_argument("--duration-ms", type=int, default=3000)
    quick.add_argument("--width", type=int, default=1080)
    quick.add_argument("--height", type=int, default=1920)
    quick.add_argument("--fit", choices=("contain", "cover"), default="contain")
    quick.add_argument("--rights-status", choices=("USER_PROVIDED", "LICENSED", "PUBLIC_DOMAIN", "GENERATED_LOCAL"), default="USER_PROVIDED")
    add_asset = sub.add_parser("import-asset", help="copy a selected file into a project asset folder")
    add_asset.add_argument("project_dir", type=Path)
    add_asset.add_argument("source", type=Path)
    add_asset.add_argument("--asset-id", required=True)
    add_asset.add_argument("--rights-status", choices=("USER_PROVIDED", "LICENSED", "PUBLIC_DOMAIN", "GENERATED_LOCAL"), default="USER_PROVIDED")
    validate = sub.add_parser("validate", help="validate a project and pinned local assets")
    validate.add_argument("project", type=Path)
    render = sub.add_parser("render", help="render a preview or final MP4 locally")
    render.add_argument("project", type=Path)
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--mode", choices=("preview", "final"), default="final")
    render.add_argument("--overwrite", action="store_true")
    inspect = sub.add_parser("inspect", help="inspect a rendered media file")
    inspect.add_argument("media", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "quickstart":
            project = create_quickstart_project(args.project_dir, args.project_id, args.media,
                                                args.duration_ms, args.width, args.height, args.fit,
                                                args.rights_status)
            result = {"status": "CREATED", "project_file": str(args.project_dir / "project.json"),
                      "project_id": project["project_id"], "scenes": len(project["scenes"]),
                      "assets": len(project["assets"])}
        elif args.command == "import-asset":
            result = import_asset(args.source, args.project_dir, args.asset_id, args.rights_status)
        elif args.command == "validate":
            project = _load(args.project)
            files = resolve_assets(project, args.project.parent)
            result = {"status": "VALID", "project_id": project["project_id"],
                      "revision": project["revision"], "assets": {k: str(v) for k, v in files.items()}}
        elif args.command == "render":
            project = _load(args.project)
            result = render_project(project, args.project.parent, args.output, args.mode, args.overwrite)
        else:
            result = probe(args.media)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProjectError, RenderError) as exc:
        print(json.dumps({"status": "ERROR", "code": getattr(exc, "code", "PROJECT_INVALID"), "message": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
