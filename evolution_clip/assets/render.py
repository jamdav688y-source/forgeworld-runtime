#!/usr/bin/env python3
"""ForgeWorld Evolution Clip — renderer.

Assembles the PNG frames in evolution_clip/frames/ into a vertical MP4
using ffmpeg's xfade filter for crossfade transitions between scenes.
No zoompan / heavy per-frame filters — keeps the filter graph small and
predictable on constrained devices (Termux).

Usage:
    python3 render.py --mode preview   # fast, small, for quick review
    python3 render.py --mode final     # full quality export
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
CLIP_DIR = ASSETS_DIR.parent
FRAMES_DIR = CLIP_DIR / "frames"
OUTPUT_DIR = CLIP_DIR / "output"

MODES = {
    "preview": {
        "width": 540, "height": 960, "fps": 20,
        "preset": "ultrafast", "crf": 30,
        "out": "preview.mp4",
    },
    "final": {
        "width": 1080, "height": 1920, "fps": 30,
        "preset": "medium", "crf": 18,
        "out": "final.mp4",
    },
}


def load_scenes():
    with open(ASSETS_DIR / "scenes.json") as f:
        return json.load(f)


def build_filter_graph(scenes, crossfade, w, h, fps):
    n = len(scenes)
    scale_pad = f"scale={w}:{h},setsar=1,fps={fps}"
    labels = []
    filters = []
    for i in range(n):
        filters.append(f"[{i}:v]{scale_pad}[s{i}]")
        labels.append(f"s{i}")

    if n == 1:
        return ";".join(filters), labels[0]

    running = labels[0]
    running_dur = scenes[0]["duration"]
    for i in range(1, n):
        nxt = labels[i]
        out_label = f"x{i}" if i < n - 1 else "vout"
        offset = running_dur - crossfade
        filters.append(
            f"[{running}][{nxt}]xfade=transition=fade:duration={crossfade:.3f}:offset={offset:.3f}[{out_label}]"
        )
        running_dur = offset + scenes[i]["duration"]
        running = out_label

    return ";".join(filters), running


def render(mode_name):
    cfg = load_scenes()
    mode = MODES[mode_name]
    scenes = cfg["scenes"]
    crossfade = cfg["crossfade_sec"]
    w, h, fps = mode["width"], mode["height"], mode["fps"]

    inputs = []
    for scene in scenes:
        frame_path = FRAMES_DIR / f"{scene['id']}.png"
        if not frame_path.exists():
            print(f"ERROR: missing frame {frame_path}. Run generate_frames.py first.", file=sys.stderr)
            sys.exit(1)
        inputs += ["-loop", "1", "-t", str(scene["duration"]), "-i", str(frame_path)]

    filter_str, final_label = build_filter_graph(scenes, crossfade, w, h, fps)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / mode["out"]

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", f"[{final_label}]",
        "-c:v", "libx264",
        "-preset", mode["preset"],
        "-crf", str(mode["crf"]),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]

    print(f"[render:{mode_name}] {len(scenes)} scenes -> {out_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-4000:], file=sys.stderr)
        sys.exit(1)

    print(f"OK: wrote {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=list(MODES), default="preview")
    args = parser.parse_args()
    render(args.mode)
