"""Frame-cache renderer: renders every frame for one aspect ratio once,
resumably, with per-frame checksums, atomic writes, disk-space checks,
and scene-chunked progress reporting.

Both preview_* and master_* profiles for the same aspect ratio read from
this same frame cache (see profiles.py) -- rendering happens once per
aspect, encoding happens per profile.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from genome.organism import draw_frame
from genome.state import TOTAL_FRAMES, SCENES, state_for_frame
from genome.typography import draw_title
from renderer.manifest import FrameManifest, atomic_write_png

FLUSH_EVERY = 24  # 1 second of footage -- resume granularity
MIN_FREE_BYTES_SAFETY_FACTOR = 1.5


class InsufficientDiskSpaceError(RuntimeError):
    def __init__(self, needed: int, available: int):
        super().__init__(f"need ~{needed} bytes free, only {available} available")
        self.needed = needed
        self.available = available


@dataclass
class RenderProgress:
    aspect_key: str
    total_frames: int
    rendered_frames: int = 0
    skipped_frames: int = 0  # already valid from a prior run (resume)
    current_scene: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished: bool = False

    def as_dict(self) -> dict:
        return {
            "aspect_key": self.aspect_key,
            "total_frames": self.total_frames,
            "rendered_frames": self.rendered_frames,
            "skipped_frames": self.skipped_frames,
            "current_scene": self.current_scene,
            "elapsed_seconds": round(self.updated_at - self.started_at, 2),
            "finished": self.finished,
            "percent": round(100 * (self.rendered_frames + self.skipped_frames) / self.total_frames, 1),
        }


def _frame_path(frames_dir: Path, frame_index: int) -> Path:
    return frames_dir / f"frame_{frame_index:06d}.png"


def _estimate_bytes_per_frame(width: int, height: int) -> int:
    # Empirical PNG size for this content is well under raw bitmap size;
    # use raw-bitmap/8 as a conservative-but-not-absurd upper estimate.
    return (width * height * 3) // 8


def render_aspect(
    aspect_key: str,
    width: int,
    height: int,
    frames_dir: Path,
    progress_path: Path | None = None,
    on_progress: Callable[[RenderProgress], None] | None = None,
) -> RenderProgress:
    """Render (or resume rendering) every frame for one aspect ratio.

    Idempotent: safe to call again after an interruption. Frames already
    present and checksum-valid are skipped; missing or corrupt frames are
    (re)rendered. Chunked by scene for progress/disk-space checkpoints.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest = FrameManifest(frames_dir / "manifest.json")
    progress = RenderProgress(aspect_key=aspect_key, total_frames=TOTAL_FRAMES)

    def _emit():
        progress.updated_at = time.time()
        if progress_path is not None:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text(json.dumps(progress.as_dict(), indent=2))
        if on_progress is not None:
            on_progress(progress)

    for scene_key, scene_label, start, end in SCENES:
        progress.current_scene = scene_key
        remaining_in_scene = end - start
        est_needed = _estimate_bytes_per_frame(width, height) * remaining_in_scene * MIN_FREE_BYTES_SAFETY_FACTOR
        free = shutil.disk_usage(frames_dir).free
        if free < est_needed:
            raise InsufficientDiskSpaceError(int(est_needed), free)

        for frame_index in range(start, end):
            frame_path = _frame_path(frames_dir, frame_index)
            if manifest.is_valid(frame_index, frame_path):
                progress.skipped_frames += 1
            else:
                state = state_for_frame(frame_index)
                img = draw_frame(state, width, height)
                img = draw_title(img, state, width, height)
                checksum = atomic_write_png(img, frame_path)
                manifest.record(frame_index, checksum)
                progress.rendered_frames += 1

            if (frame_index + 1) % FLUSH_EVERY == 0:
                manifest.save()
                _emit()

        manifest.save()
        _emit()

    progress.finished = True
    _emit()
    return progress


def verify_frame_cache(frames_dir: Path) -> dict:
    """Post-render integrity check: every frame 0..2159 present and valid
    per the manifest. Used by the preview gate."""
    manifest = FrameManifest(frames_dir / "manifest.json")
    missing = []
    corrupt = []
    for frame_index in range(TOTAL_FRAMES):
        frame_path = _frame_path(frames_dir, frame_index)
        if not frame_path.exists():
            missing.append(frame_index)
            continue
        if str(frame_index) not in manifest.entries:
            corrupt.append(frame_index)
            continue
        if not manifest.is_valid(frame_index, frame_path):
            corrupt.append(frame_index)
    return {
        "total_frames": TOTAL_FRAMES,
        "present": TOTAL_FRAMES - len(missing),
        "missing_frames": missing,
        "corrupt_frames": corrupt,
        "ok": not missing and not corrupt,
    }
