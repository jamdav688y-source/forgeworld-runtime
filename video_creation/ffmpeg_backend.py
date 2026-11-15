"""Bounded local rendering through the user's installed FFmpeg tools."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from fractions import Fraction
from pathlib import Path

from .plan import compile_render_plan
from .project import ProjectError, canonical_project_bytes, resolve_assets, sha256_file
from .receipt import write_receipt


class RenderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RenderError("TOOL_MISSING", f"{name} is required; install it locally and ensure it is on PATH")
    return str(Path(path).resolve())


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        raise RenderError("TOOL_TIMEOUT", f"command timed out after {timeout} seconds: {Path(args[0]).name}") from None
    except OSError as exc:
        raise RenderError("TOOL_LAUNCH_FAILED", f"could not launch local media tool: {exc}") from None


def _version(ffmpeg: str) -> str:
    proc = _run([ffmpeg, "-version"], 10)
    if proc.returncode != 0:
        raise RenderError("TOOL_UNAVAILABLE", proc.stderr[-1000:])
    return (proc.stdout.splitlines() or ["unknown"])[0]


def doctor() -> dict:
    ffmpeg, ffprobe = _tool("ffmpeg"), _tool("ffprobe")
    version = _version(ffmpeg)
    filters = _run([ffmpeg, "-hide_banner", "-filters"], 20)
    encoders = _run([ffmpeg, "-hide_banner", "-encoders"], 20)
    buildconf = _run([ffmpeg, "-hide_banner", "-buildconf"], 20)
    if filters.returncode or encoders.returncode or buildconf.returncode:
        raise RenderError("CAPABILITY_PROBE_FAILED", "FFmpeg filter or encoder discovery failed")
    filter_text, encoder_text = filters.stdout + filters.stderr, encoders.stdout + encoders.stderr
    missing = [name for name in ("scale", "crop", "pad", "fps", "concat", "drawtext", "zoompan") if name not in filter_text]
    missing += [name for name in ("libx264", "aac") if name not in encoder_text]
    font = _find_font()
    if font is None:
        missing.append("font")
    return {
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "version": version,
        "build_configuration": buildconf.stdout + buildconf.stderr,
        "gpl_enabled": "--enable-gpl" in (buildconf.stdout + buildconf.stderr),
        "nonfree_enabled": "--enable-nonfree" in (buildconf.stdout + buildconf.stderr),
        "required_features": {"scale": "scale" in filter_text, "crop": "crop" in filter_text,
                              "pad": "pad" in filter_text, "fps": "fps" in filter_text,
                              "concat": "concat" in filter_text, "drawtext": "drawtext" in filter_text,
                              "zoompan": "zoompan" in filter_text,
                              "libx264": "libx264" in encoder_text, "aac": "aac" in encoder_text,
                              "font": font is not None},
        "font": font,
        "missing_features": missing,
    }


def probe(path: Path, ffprobe: str | None = None) -> dict:
    ffprobe = ffprobe or _tool("ffprobe")
    proc = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], 30)
    if proc.returncode != 0:
        raise RenderError("PROBE_FAILED", proc.stderr[-1500:] or "ffprobe could not read media")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RenderError("PROBE_INVALID_JSON", "ffprobe returned invalid JSON") from None


def _filter_escape(value: str) -> str:
    """Escape values for FFmpeg's filter-option parser, not a command shell."""
    chars = {"\\": "\\\\", "'": "\\'", ":": "\\:", ",": "\\,", "[": "\\[", "]": "\\]"}
    return "".join(chars.get(char, char) for char in value)


def _quote(value: str) -> str:
    return "'" + _filter_escape(value) + "'"


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.6f}"


def _fit_filters(width: int, height: int, fit: str) -> str:
    if fit == "cover":
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"


def _find_font() -> str | None:
    prefix = os.environ.get("PREFIX", "")
    candidates = [Path(os.environ["FW_VIDEO_FONT"])] if os.environ.get("FW_VIDEO_FONT") else []
    if prefix:
        candidates.extend([Path(prefix) / "share/fonts/TTF/DejaVuSans.ttf",
                           Path(prefix) / "share/fonts/truetype/dejavu/DejaVuSans.ttf",
                           Path(prefix) / "share/fonts/TTF/LiberationSans-Regular.ttf"])
    candidates.extend([
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ])
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _format_srt_time(ms: int) -> str:
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, millis = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _srt_content(project: dict, plan: dict) -> str:
    rows = []
    offset = 0
    cue_number = 1
    for scene, planned in zip(project["scenes"], plan["scenes"]):
        duration_ms = round(float(Fraction(planned["duration_num"], planned["duration_den"])) * 1000)
        for cue in scene["captions"]:
            start = offset + cue["start_ms"]
            end = min(offset + duration_ms, offset + cue["end_ms"])
            rows.extend([str(cue_number), f"{_format_srt_time(start)} --> {_format_srt_time(end)}", cue["text"], ""])
            cue_number += 1
        offset += duration_ms
    return "\n".join(rows)


def _validate_sources(project: dict, files: dict[str, Path], ffprobe: str, plan: dict) -> None:
    assets = {asset["asset_id"]: asset for asset in project["assets"]}
    for scene, planned in zip(project["scenes"], plan["scenes"]):
        asset = assets[scene["asset_id"]]
        data = probe(files[asset["asset_id"]], ffprobe)
        streams = data.get("streams", [])
        has_video = any(stream.get("codec_type") == "video" for stream in streams)
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        if asset["kind"] == "image" and not has_video:
            raise RenderError("ASSET_STREAM_MISMATCH", f"asset {asset['asset_id']} is not a readable image/video stream")
        if asset["kind"] == "video" and not has_video:
            raise RenderError("ASSET_STREAM_MISMATCH", f"asset {asset['asset_id']} has no video stream")
        if asset["kind"] == "audio" and not has_audio:
            raise RenderError("ASSET_STREAM_MISMATCH", f"asset {asset['asset_id']} has no audio stream")
        if asset["kind"] == "video":
            duration = float(data.get("format", {}).get("duration", 0) or 0)
            requested = (scene["source_in_ms"] / 1000) + float(planned["duration_seconds"])
            if requested > duration + 0.05:
                raise RenderError("SOURCE_RANGE_INVALID", f"scene {scene['scene_id']} requests {requested:.3f}s from a {duration:.3f}s source")
        if asset["kind"] == "image" and scene["source_in_ms"] != 0:
            raise RenderError("SOURCE_RANGE_INVALID", f"image scene {scene['scene_id']} must start at zero")
    if project["audio"] is not None:
        asset = assets[project["audio"]["asset_id"]]
        data = probe(files[asset["asset_id"]], ffprobe)
        if not any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])):
            raise RenderError("ASSET_STREAM_MISMATCH", f"asset {asset['asset_id']} has no audio stream")


def _build_command(project: dict, plan: dict, files: dict[str, Path], work: Path, output: Path, ffmpeg: str, preview: bool) -> tuple[list[str], Path | None]:
    profile = plan["profile"]
    fps = f"{profile['fps_num']}/{profile['fps_den']}"
    args = [ffmpeg, "-hide_banner", "-y", "-nostdin"]
    for scene, planned in zip(project["scenes"], plan["scenes"]):
        path = files[scene["asset_id"]]
        asset = next(a for a in project["assets"] if a["asset_id"] == scene["asset_id"])
        duration = planned["duration_seconds"]
        if asset["kind"] == "image":
            args += ["-loop", "1", "-framerate", fps, "-t", duration, "-i", str(path)]
        else:
            args += ["-ss", _seconds(scene["source_in_ms"]), "-t", duration, "-i", str(path)]
    audio_index = None
    if project["audio"] is not None:
        audio_index = len(project["scenes"])
        args += ["-i", str(files[project["audio"]["asset_id"]])]

    font = _find_font()
    if font is None:
        raise RenderError("FONT_MISSING", "install a TrueType font supported by FFmpeg drawtext")
    filters = []
    for i, (scene, planned) in enumerate(zip(project["scenes"], plan["scenes"])):
        width, height = profile["width"], profile["height"]
        asset_kind = next(a["kind"] for a in project["assets"] if a["asset_id"] == scene["asset_id"])
        motion = scene.get("motion", "static")
        camera = ""
        if asset_kind == "image" and motion != "static":
            last_frame = max(1, planned["frame_count"] - 1)
            if motion == "push_in":
                expression = f"z=1+0.05*on/{last_frame}"
            elif motion == "pull_out":
                expression = f"z=1.05-0.05*on/{last_frame}"
            elif motion == "pan_left":
                expression = f"z=1.06:x=(iw-iw/zoom)*(1-on/{last_frame}):y=ih/2-ih/zoom/2"
            else:  # pan_right
                expression = f"z=1.06:x=(iw-iw/zoom)*on/{last_frame}:y=ih/2-ih/zoom/2"
            camera = f",zoompan={expression}:d=1:s={width}x{height}:fps={fps}"
        base = (f"[{i}:v]trim=duration={planned['duration_seconds']},setpts=PTS-STARTPTS,"
                f"{_fit_filters(width, height, planned['fit'])}{camera},fps={fps},format=yuv420p")
        label_text = planned["label"].replace("_", " ")
        overlay = planned["overlay_text"].strip()
        text = label_text + ("\n" + overlay if overlay else "")
        text_path = work / f"scene-{i:03d}.txt"
        text_path.write_text(text, encoding="utf-8")
        # FFmpeg parses filter paths with its own escaping grammar. Resolve the
        # generated text by a safe basename and run FFmpeg from this job's
        # directory, so user-controlled output-directory punctuation never
        # enters the filtergraph.
        draw = (f"drawtext=fontfile={_quote(font)}:textfile={_quote(text_path.name)}:expansion=none:"
                f"fontcolor=white:fontsize={max(20, height // 22)}:line_spacing=10:"
                "box=1:boxcolor=black@0.58:boxborderw=18:x=(w-text_w)/2:y=h-text_h-64:fix_bounds=1")
        filters.append(f"{base},{draw}[v{i}]")
    concat_inputs = "".join(f"[v{i}]" for i in range(len(project["scenes"])))
    filters.append(f"{concat_inputs}concat=n={len(project['scenes'])}:v=1:a=0[vout]")
    total = plan["total_duration_seconds"]
    if audio_index is not None:
        audio = project["audio"]
        chain = f"[{audio_index}:a]atrim=duration={total},asetpts=PTS-STARTPTS,volume={float(audio['gain']):.4f},apad,atrim=duration={total}"
        if audio["fade_out_ms"] > 0:
            fade = audio["fade_out_ms"] / 1000
            start = max(0.0, float(total) - fade)
            chain += f",afade=t=out:st={start:.6f}:d={fade:.6f}"
        filters.append(chain + "[aout]")

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio_index is not None:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    args += ["-c:v", "libx264", "-preset", "veryfast" if preview else "medium", "-crf", str(profile["crf"]),
             "-pix_fmt", "yuv420p", "-r", fps, "-movflags", "+faststart", "-t", total, str(output)]
    srt_path = work / "captions.srt" if any(s["captions"] for s in project["scenes"]) else None
    if srt_path:
        srt_path.write_text(_srt_content(project, plan), encoding="utf-8")
    return args, srt_path


def _validate_output(path: Path, ffprobe: str, plan: dict, audio_expected: bool) -> dict:
    data = probe(path, ffprobe)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RenderError("OUTPUT_VIDEO_MISSING", "rendered output has no video stream")
    expected = plan["profile"]
    if int(video.get("width", 0)) != expected["width"] or int(video.get("height", 0)) != expected["height"]:
        raise RenderError("OUTPUT_DIMENSIONS_MISMATCH", "rendered dimensions do not match the project profile")
    actual_duration = float(data.get("format", {}).get("duration", 0) or 0)
    expected_duration = float(plan["total_duration_seconds"])
    frame = expected["fps_den"] / expected["fps_num"]
    if actual_duration <= 0 or abs(actual_duration - expected_duration) > frame + 0.05:
        raise RenderError("OUTPUT_DURATION_MISMATCH", f"output duration {actual_duration:.3f}s differs from expected {expected_duration:.3f}s")
    if audio_expected and audio is None:
        raise RenderError("OUTPUT_AUDIO_MISSING", "project requested audio but output has no audio stream")
    if video.get("pix_fmt") != "yuv420p":
        raise RenderError("OUTPUT_PIXEL_FORMAT_MISMATCH", f"unexpected output pixel format: {video.get('pix_fmt')}")
    return {"format": data.get("format", {}), "video": video, "audio": audio}


def render_project(project: dict, project_dir: Path, output_path: Path, mode: str = "final", overwrite: bool = False,
                   timeout_seconds: int = 900, cancel_event: threading.Event | None = None) -> dict:
    """Render locally, verify with ffprobe, then atomically publish the file to its output path."""
    if mode not in {"preview", "final"}:
        raise ProjectError("mode must be preview or final")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
        raise ProjectError("timeout_seconds must be from 1 through 3600")
    ffmpeg, ffprobe = _tool("ffmpeg"), _tool("ffprobe")
    tool_info = doctor()
    if tool_info["missing_features"]:
        raise RenderError("FEATURES_MISSING", ", ".join(tool_info["missing_features"]))
    preview = mode == "preview"
    plan = compile_render_plan(project, preview=preview)
    files = resolve_assets(project, Path(project_dir))
    _validate_sources(project, files, ffprobe, plan)

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() != ".mp4":
        raise ProjectError("output path must end in .mp4")
    receipt_path = output.with_suffix(output.suffix + ".receipt.json")
    expected_srt = output.with_suffix(".srt") if any(s["captions"] for s in project["scenes"]) else None
    if not overwrite and (output.exists() or receipt_path.exists() or (expected_srt and expected_srt.exists())):
        raise RenderError("OUTPUT_EXISTS", "output or receipt exists; pass overwrite=True to replace it")

    work = Path(tempfile.mkdtemp(prefix=f".fw-video-{project['project_id']}-", dir=output.parent))
    temporary_output = work / "render.partial.mp4"
    started = time.monotonic()
    stderr = ""
    try:
        args, temp_srt = _build_command(project, plan, files, work, temporary_output, ffmpeg, preview)
        try:
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, shell=False, cwd=work)
        except OSError as exc:
            raise RenderError("RENDER_LAUNCH_FAILED", f"could not launch FFmpeg: {exc}") from None
        deadline = time.monotonic() + timeout_seconds
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                _, stderr = process.communicate()
                raise RenderError("RENDER_CANCELLED", "render was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                _, stderr = process.communicate()
                raise RenderError("RENDER_TIMEOUT", f"render exceeded {timeout_seconds}s")
            try:
                _, stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0 or not temporary_output.is_file() or temporary_output.stat().st_size == 0:
            raise RenderError("RENDER_FAILED", (stderr or "FFmpeg produced no output")[-3000:])
        output_probe = _validate_output(temporary_output, ffprobe, plan, project["audio"] is not None)
        digest = sha256_file(temporary_output)
        srt_target = output.with_suffix(".srt") if temp_srt else None
        if temp_srt:
            # Copy into the job directory so the sidecar is promoted atomically too.
            staged_srt = work / "captions.final.srt"
            shutil.copyfile(temp_srt, staged_srt)
        else:
            staged_srt = None
        staged_receipt = work / "render.receipt.json"
        receipt = write_receipt(
            project=project,
            plan=plan,
            output_path=output,
            output_sha256=digest,
            output_probe=output_probe,
            tool_info=tool_info,
            mode=mode,
            elapsed_seconds=time.monotonic() - started,
            receipt_path=staged_receipt,
            captions_path=staged_srt,
        )
        os.replace(temporary_output, output)
        if staged_srt is not None and srt_target is not None:
            os.replace(staged_srt, srt_target)
        os.replace(staged_receipt, receipt_path)
        return {"status": "RENDERED", "output_path": str(output), "receipt_path": str(receipt_path),
                "captions_path": str(srt_target) if srt_target else None, "output_sha256": digest,
                "plan": plan, "receipt": receipt, "elapsed_seconds": round(time.monotonic() - started, 3)}
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError("RENDER_INTERNAL_ERROR", f"{type(exc).__name__}: {exc}") from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
