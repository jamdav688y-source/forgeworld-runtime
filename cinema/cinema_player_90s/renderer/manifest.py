"""Frame checksum manifest: what makes rendering resumable and corruption-
detecting. One manifest per aspect-ratio frame cache.

The manifest is the single source of truth for "is this frame already
correctly rendered." A frame is considered valid only if:
  1. its entry exists in the manifest, AND
  2. its PNG file exists on disk, AND
  3. the live sha256 of that file matches the manifest's recorded hash.

Any other state (missing entry, missing file, or a checksum mismatch --
e.g. a truncated file from a mid-write kill) is treated as "needs
(re)render," which is what gives us missing-frame recovery and
corrupt-frame detection for free from the same mechanism.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class FrameManifest:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, str] = {}  # str(frame_index) -> sha256
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                # A manifest corrupted by an interrupted write is treated as
                # empty -- every frame will be re-verified against disk
                # individually, which is safe (idempotent) even if slower.
                self.entries = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.entries, indent=0))
        os.replace(tmp, self.path)  # atomic on POSIX

    def is_valid(self, frame_index: int, frame_path: Path) -> bool:
        key = str(frame_index)
        recorded = self.entries.get(key)
        if recorded is None or not frame_path.exists():
            return False
        try:
            return _sha256_file(frame_path) == recorded
        except OSError:
            return False

    def record(self, frame_index: int, checksum: str) -> None:
        self.entries[str(frame_index)] = checksum

    def __len__(self) -> int:
        return len(self.entries)


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_png(img, dest: Path) -> str:
    """Write a PIL image atomically (tmp file + rename) and return its
    sha256. Never leaves a partially-written file at `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    img.save(tmp, "PNG", compress_level=3)
    os.replace(tmp, dest)
    return _sha256_file(dest)
