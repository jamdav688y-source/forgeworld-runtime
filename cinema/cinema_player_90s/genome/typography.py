"""Scene-title typography overlay.

Every scene's title fades in over its first ~15% and fades out over its
last ~15%, safe-margined so it's never clipped in either 16:9 or 4:5.
Uses DejaVu Sans (present on this system; a standard Linux font, not a
custom asset) -- no external font files are bundled.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from genome.state import CognitiveState

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _font_cache:
        for candidate in _FONT_CANDIDATES:
            if Path(candidate).exists():
                _font_cache[size] = ImageFont.truetype(candidate, size)
                break
        else:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def _fade_alpha(scene_progress: float, fade_frac: float = 0.15) -> float:
    if scene_progress < fade_frac:
        return scene_progress / fade_frac
    if scene_progress > 1 - fade_frac:
        return (1 - scene_progress) / fade_frac
    return 1.0


def draw_title(img: Image.Image, state: CognitiveState, width: int, height: int) -> Image.Image:
    alpha = _fade_alpha(state.scene_progress)
    if alpha <= 0.01:
        return img

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(14, int(min(width, height) * 0.032))
    font = _font(font_size)
    text = state.scene_label.upper()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    margin = int(height * 0.06)
    x = (width - text_w) / 2
    y = height - margin - (bbox[3] - bbox[1])

    a = int(230 * alpha)
    draw.text((x, y), text, font=font, fill=(240, 244, 250, a))

    small_font = _font(max(10, int(font_size * 0.42)))
    subtitle = f"scene {_scene_number(state.scene_key)} / 9"
    sub_bbox = draw.textbbox((0, 0), subtitle, font=small_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text(
        ((width - sub_w) / 2, y - (sub_bbox[3] - sub_bbox[1]) - int(height * 0.012)),
        subtitle, font=small_font, fill=(200, 210, 225, int(180 * alpha)),
    )

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _scene_number(scene_key: str) -> int:
    from genome.state import SCENES
    for i, (key, *_rest) in enumerate(SCENES, start=1):
        if key == scene_key:
            return i
    return 0
