#!/usr/bin/env python3
"""ForgeWorld Evolution Clip — provenance manifest.

Writes evolution_clip/output/manifest.json and MANIFEST.md listing, for
every scene: the generated frame, its render kind/duration, and the
exact repo source files it draws on (with sha256 + git blob hash so the
citation is checkable, not just asserted). Also records the tool
versions and git commit the clip was built from.

Run after generate_frames.py (and, optionally, after render.py so the
output video files can be recorded too).
"""
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
CLIP_DIR = ASSETS_DIR.parent
REPO_ROOT = CLIP_DIR.parent
FRAMES_DIR = CLIP_DIR / "frames"
OUTPUT_DIR = CLIP_DIR / "output"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args, default=""):
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception:
        return default


def tool_version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
        return (out.stdout or out.stderr).splitlines()[0].strip()
    except Exception:
        return "unavailable"


def pil_version():
    try:
        import PIL
        return PIL.__version__
    except Exception:
        return "unavailable"


def main():
    with open(ASSETS_DIR / "scenes.json") as f:
        scenes_cfg = json.load(f)

    commit = git("rev-parse", "HEAD", default="unknown")
    branch = git("rev-parse", "--abbrev-ref", "HEAD", default="unknown")
    dirty = bool(git("status", "--porcelain"))

    scene_entries = []
    all_sources = {}

    for scene in scenes_cfg["scenes"]:
        frame_path = FRAMES_DIR / f"{scene['id']}.png"
        frame_info = None
        if frame_path.exists():
            frame_info = {
                "path": str(frame_path.relative_to(REPO_ROOT)),
                "sha256": sha256_of(frame_path),
                "bytes": frame_path.stat().st_size,
            }

        sources = []
        for rel in scene.get("source_files", []):
            abs_path = REPO_ROOT / rel
            if abs_path.exists():
                blob_hash = git("hash-object", str(abs_path), default="unknown")
                entry = {
                    "path": rel,
                    "exists": True,
                    "sha256": sha256_of(abs_path),
                    "git_blob_sha1": blob_hash,
                    "bytes": abs_path.stat().st_size,
                }
            else:
                entry = {"path": rel, "exists": False}
            sources.append(entry)
            all_sources[rel] = entry

        scene_entries.append({
            "id": scene["id"],
            "kind": scene["kind"],
            "duration_sec": scene["duration"],
            "generated_frame": frame_info,
            "provenance_note": scene.get("provenance_note"),
            "source_files": sources,
        })

    outputs = {}
    for name in ("preview.mp4", "final.mp4"):
        p = OUTPUT_DIR / name
        if p.exists():
            outputs[name] = {
                "path": str(p.relative_to(REPO_ROOT)),
                "sha256": sha256_of(p),
                "bytes": p.stat().st_size,
            }

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "commit": commit,
            "branch": branch,
            "working_tree_dirty": dirty,
        },
        "toolchain": {
            "python": sys.version.split()[0],
            "pillow": pil_version(),
            "ffmpeg": tool_version(["ffmpeg", "-version"]),
            "platform": platform.platform(),
        },
        "canvas": scenes_cfg["canvas"],
        "crossfade_sec": scenes_cfg["crossfade_sec"],
        "total_scripted_duration_sec": round(
            sum(s["duration"] for s in scenes_cfg["scenes"]), 2
        ),
        "scene_count": len(scene_entries),
        "unique_source_file_count": len(all_sources),
        "scenes": scene_entries,
        "outputs": outputs,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    write_markdown(manifest)
    print(f"wrote {OUTPUT_DIR / 'manifest.json'}")
    print(f"wrote {OUTPUT_DIR / 'MANIFEST.md'}")


def write_markdown(manifest):
    lines = []
    lines.append("# ForgeWorld Evolution Clip — Asset Manifest")
    lines.append("")
    lines.append(f"Generated: {manifest['generated_at_utc']}")
    lines.append(f"Repo commit: `{manifest['repo']['commit']}` (branch `{manifest['repo']['branch']}`"
                  f"{', dirty working tree' if manifest['repo']['working_tree_dirty'] else ''})")
    lines.append(f"Toolchain: Python {manifest['toolchain']['python']} · "
                 f"Pillow {manifest['toolchain']['pillow']} · {manifest['toolchain']['ffmpeg']}")
    lines.append(f"Canvas: {manifest['canvas']['width']}x{manifest['canvas']['height']} · "
                 f"{manifest['scene_count']} scenes · "
                 f"~{manifest['total_scripted_duration_sec']}s scripted "
                 f"(crossfade {manifest['crossfade_sec']}s each)")
    lines.append("")
    lines.append("Every frame below is generated (not stock/found footage). Where a scene")
    lines.append("displays repo content, the exact source file(s) and their content hash")
    lines.append("at generation time are listed so the citation can be independently")
    lines.append("checked against the repo history.")
    lines.append("")

    for s in manifest["scenes"]:
        lines.append(f"## `{s['id']}` — {s['kind']} ({s['duration_sec']}s)")
        if s["generated_frame"]:
            lines.append(f"- Frame: `{s['generated_frame']['path']}` "
                         f"(sha256 `{s['generated_frame']['sha256'][:12]}…`, "
                         f"{s['generated_frame']['bytes']} bytes)")
        if s["provenance_note"]:
            lines.append(f"- Note: {s['provenance_note']}")
        if s["source_files"]:
            lines.append("- Sources:")
            for src in s["source_files"]:
                if src["exists"]:
                    lines.append(f"  - `{src['path']}` — git blob `{src['git_blob_sha1'][:12]}…`, "
                                 f"sha256 `{src['sha256'][:12]}…`, {src['bytes']} bytes")
                else:
                    lines.append(f"  - `{src['path']}` — MISSING at generation time")
        else:
            lines.append("- Sources: none (original creative-brief text)")
        lines.append("")

    if manifest["outputs"]:
        lines.append("## Rendered outputs")
        for name, info in manifest["outputs"].items():
            lines.append(f"- `{info['path']}` — sha256 `{info['sha256'][:12]}…`, {info['bytes']} bytes")
        lines.append("")

    with open(OUTPUT_DIR / "MANIFEST.md", "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
