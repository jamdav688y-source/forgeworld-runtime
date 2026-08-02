"""ffmpeg encode + ffprobe-verified atomic promotion.

Never infer success from an ffmpeg exit code alone: after encoding, this
module runs ffprobe with -count_frames (forces an actual decode of every
frame, not a header read) and only promotes the `.partial` output to its
final path if the decoded properties match MASTER_SPEC exactly. If they
don't, the `.partial` file is left in place for inspection and the
caller gets a structured failure.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

FPS = 24
TOTAL_FRAMES = 2160
DURATION_SECONDS = 90.0


@dataclass
class ProbeResult:
    raw: dict
    video_codec: str | None
    pix_fmt: str | None
    width: int | None
    height: int | None
    r_frame_rate: str | None
    avg_frame_rate: str | None
    decoded_frame_count: int | None
    duration_seconds: float | None
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    bit_rate: int | None
    file_size_bytes: int | None


def ffprobe_validate(path: Path) -> ProbeResult:
    cmd = [
        "ffprobe", "-v", "error",
        "-count_frames",
        "-show_entries",
        "stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate,avg_frame_rate,"
        "nb_read_frames,sample_rate,channels,bit_rate:format=duration,bit_rate,size",
        "-of", "json",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {out.stderr}")
    data = json.loads(out.stdout)

    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})

    return ProbeResult(
        raw=data,
        video_codec=video.get("codec_name"),
        pix_fmt=video.get("pix_fmt"),
        width=video.get("width"),
        height=video.get("height"),
        r_frame_rate=video.get("r_frame_rate"),
        avg_frame_rate=video.get("avg_frame_rate"),
        decoded_frame_count=int(video["nb_read_frames"]) if video.get("nb_read_frames") else None,
        duration_seconds=float(fmt["duration"]) if fmt.get("duration") else None,
        audio_codec=audio.get("codec_name"),
        audio_sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        audio_channels=audio.get("channels"),
        bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        file_size_bytes=int(fmt["size"]) if fmt.get("size") else path.stat().st_size if path.exists() else None,
    )


def spec_check(probe: ProbeResult, expected_width: int, expected_height: int) -> list[str]:
    """Returns a list of human-readable violations; empty list = passes."""
    problems = []
    if probe.decoded_frame_count != TOTAL_FRAMES:
        problems.append(f"decoded_frame_count={probe.decoded_frame_count}, expected {TOTAL_FRAMES}")
    if probe.duration_seconds is None or abs(probe.duration_seconds - DURATION_SECONDS) > 0.05:
        problems.append(f"duration={probe.duration_seconds}, expected {DURATION_SECONDS}")
    if probe.r_frame_rate != f"{FPS}/1":
        problems.append(f"r_frame_rate={probe.r_frame_rate}, expected {FPS}/1")
    if probe.avg_frame_rate != f"{FPS}/1":
        problems.append(f"avg_frame_rate={probe.avg_frame_rate}, expected {FPS}/1")
    if probe.width != expected_width or probe.height != expected_height:
        problems.append(f"resolution={probe.width}x{probe.height}, expected {expected_width}x{expected_height}")
    if probe.video_codec != "h264":
        problems.append(f"video_codec={probe.video_codec}, expected h264")
    if probe.pix_fmt != "yuv420p":
        problems.append(f"pix_fmt={probe.pix_fmt}, expected yuv420p")
    if probe.audio_codec != "aac":
        problems.append(f"audio_codec={probe.audio_codec}, expected aac")
    if probe.audio_sample_rate != 48000:
        problems.append(f"audio_sample_rate={probe.audio_sample_rate}, expected 48000")
    if probe.audio_channels != 2:
        problems.append(f"audio_channels={probe.audio_channels}, expected 2")
    return problems


def encode(
    frames_dir: Path,
    audio_wav: Path,
    out_path: Path,
    width: int,
    height: int,
    crf: int,
    preset: str,
) -> tuple[bool, ProbeResult | None, list[str]]:
    """Encode frames_dir/frame_%06d.png + audio_wav to out_path via a
    `.partial` intermediate, validate with ffprobe, and only then
    atomically promote. Returns (success, probe_result_or_None, problems)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.stem + ".partial" + out_path.suffix)

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-start_number", "0",
        "-i", str(frames_dir / "frame_%06d.png"),
        "-i", str(audio_wav),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-vsync", "cfr",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", str(DURATION_SECONDS),
        str(partial),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        return False, None, [f"ffmpeg exited {result.returncode}: {result.stderr[-2000:]}"]

    probe = ffprobe_validate(partial)
    problems = spec_check(probe, width, height)
    if problems:
        # leave .partial in place for inspection -- do not promote
        return False, probe, problems

    os.replace(partial, out_path)  # atomic promotion of validated output
    final_probe = ffprobe_validate(out_path)
    return True, final_probe, []
