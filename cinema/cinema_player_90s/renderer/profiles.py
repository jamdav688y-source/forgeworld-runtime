"""Render profiles. Every profile is parameterized -- no 1280x720 (or any
other resolution) is hardcoded anywhere in the renderer itself; profiles
are the only place resolution lives.

preview_* and master_* share the same resolution/aspect on purpose: the
preview and master differ in encode settings (see renderer/encode.py),
not in rendered content, so the operator's preview is pixel-identical to
what ships (this is also why the renderer caches frames per *aspect*,
not per profile -- see render.py's FRAME_CACHE_KEY).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    width: int
    height: int
    aspect_key: str  # which frame cache this profile's frames belong to
    quality: str      # draft | preview | master
    crf: int          # x264 constant rate factor (lower = higher quality)
    preset: str        # x264 preset


PROFILES: dict[str, Profile] = {
    "draft": Profile("draft", 480, 270, "draft", "draft", crf=30, preset="ultrafast"),
    "preview_16x9": Profile("preview_16x9", 1920, 1080, "16x9", "preview", crf=23, preset="veryfast"),
    "preview_4x5": Profile("preview_4x5", 1080, 1350, "4x5", "preview", crf=23, preset="veryfast"),
    "master_16x9": Profile("master_16x9", 1920, 1080, "16x9", "master", crf=17, preset="slow"),
    "master_4x5": Profile("master_4x5", 1080, 1350, "4x5", "master", crf=17, preset="slow"),
}


def get_profile(name: str) -> Profile:
    if name not in PROFILES:
        raise ValueError(f"unknown profile '{name}', valid: {sorted(PROFILES)}")
    return PROFILES[name]
