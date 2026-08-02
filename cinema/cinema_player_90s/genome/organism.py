"""Procedural visual primitives: 'the organism'.

Deterministic, seed-based particle/node-graph system. No external image
or video assets -- every pixel is drawn by PIL from the CognitiveState
values for that frame. This is honestly geometric/abstract motion
graphics, not footage from a video-generation model or an artist-directed
production (see MASTER_SPEC.md / REVIEWS/artistic_review.md).

Camera handling: instead of rendering to a fixed square and letterboxing
per aspect ratio, `draw_frame` computes the visible world-space window
directly from the *output* aspect ratio at the requested zoom, so both
16:9 and 4:5 are native full-bleed compositions with no black bars, and
zooming out never runs out of background because the background gradient
is painted across the full computed view window, not a fixed-size asset.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
import random
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from genome.state import CognitiveState, TOTAL_FRAMES

SEED_BASE = 90210  # deterministic across every run and every aspect ratio

# Palette keyframes (RGB 0-255) the film moves through as palette_t: 0 -> 1.
_PALETTE_STOPS = [
    (0.00, (12, 14, 24)),    # latent -- near-black indigo
    (0.15, (18, 28, 56)),    # sensory -- deep blue
    (0.35, (24, 64, 96)),    # convergence -- teal-blue
    (0.50, (36, 96, 84)),    # competition/construction -- teal-green
    (0.65, (74, 132, 88)),   # construction/testing -- green
    (0.80, (168, 150, 72)),  # emergence -- amber
    (0.92, (214, 122, 64)),  # release -- warm orange
    (1.00, (232, 208, 168)), # recursion -- warm light
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _palette_color(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    for i in range(len(_PALETTE_STOPS) - 1):
        t0, c0 = _PALETTE_STOPS[i]
        t1, c1 = _PALETTE_STOPS[i + 1]
        if t0 <= t <= t1:
            local = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return tuple(int(round(_lerp(c0[i2], c1[i2], local))) for i2 in range(3))
    return _PALETTE_STOPS[-1][1]


def _accent_color(t: float) -> tuple[int, int, int]:
    base = _palette_color(t)
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in base))
    h = (h + 0.5) % 1.0
    l = min(0.85, l + 0.35)
    s = min(1.0, s + 0.2)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


@dataclass
class ViewWindow:
    """World-space box currently visible, computed per output aspect ratio."""
    cx: float
    cy: float
    half_w: float
    half_h: float

    def to_px(self, x: float, y: float, width: int, height: int) -> tuple[float, float]:
        u = (x - (self.cx - self.half_w)) / (2 * self.half_w)
        v = (y - (self.cy - self.half_h)) / (2 * self.half_h)
        return u * width, v * height

    def scale_px(self, r: float, width: int) -> float:
        return r / (2 * self.half_w) * width


def _view_window(state: CognitiveState, aspect_ratio: float) -> ViewWindow:
    # camera_distance in [0,1] -> world half-height in [0.35, 1.35]
    base_half_h = 0.35 + state.camera_distance * 1.0
    half_h = base_half_h
    half_w = half_h * aspect_ratio
    # slow orbit of the view center, small enough to always keep the
    # organism's core inside frame regardless of aspect ratio
    drift = 0.06 * (state.organism_maturity - 0.5)
    cx = 0.5 + drift * math.cos(state.frame / TOTAL_FRAMES * math.pi)
    cy = 0.5 + drift * math.sin(state.frame / TOTAL_FRAMES * math.pi * 1.3)
    return ViewWindow(cx=cx, cy=cy, half_w=half_w, half_h=half_h)


def _node_layout(scene_key: str, count: int) -> list[tuple[float, float, float]]:
    """Deterministic node positions for a scene: (x, y, radius_weight) in
    world space, seeded from the scene name so every frame of the same
    scene reuses the same node positions (only their drawn state changes)."""
    seed = SEED_BASE ^ (hash(scene_key) & 0xFFFFFFFF)
    rng = random.Random(seed)
    nodes = []
    for _ in range(count):
        angle = rng.uniform(0, 2 * math.pi)
        radius = rng.uniform(0.05, 0.42) * (0.6 + 0.4 * rng.random())
        x = 0.5 + radius * math.cos(angle)
        y = 0.5 + radius * math.sin(angle) * 0.9
        weight = rng.uniform(0.4, 1.0)
        nodes.append((x, y, weight))
    return nodes


@lru_cache(maxsize=8)
def _pixel_grid(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Cached per output resolution: pixel-center coordinates in [0,1]x[0,1]
    normalized-to-width units, reused every frame (only the view window
    changes, not the grid itself)."""
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    return xs, ys


def _background_array(view: ViewWindow, width: int, height: int, base_color: tuple[int, int, int]) -> np.ndarray:
    """Vectorized radial gradient covering the full frame -- numpy instead
    of dozens of PIL ellipse draws, since this is the hottest path when
    rendering thousands of frames."""
    xs, ys = _pixel_grid(width, height)
    cx_px, cy_px = view.to_px(view.cx, view.cy, width, height)
    diag_px = view.scale_px(math.hypot(view.half_w, view.half_h), width)
    dist = np.sqrt((xs - cx_px) ** 2 + (ys - cy_px) ** 2)
    t = np.clip(dist / max(diag_px, 1.0), 0.0, 1.0)
    shade = 0.35 + 0.65 * (1 - t)
    out = np.empty((height, width, 3), dtype=np.uint8)
    for c in range(3):
        out[:, :, c] = np.clip(base_color[c] * shade, 0, 255).astype(np.uint8)
    return out


def draw_frame(state: CognitiveState, width: int, height: int) -> Image.Image:
    aspect_ratio = width / height
    view = _view_window(state, aspect_ratio)

    base_color = _palette_color(state.palette_t)
    accent_color = _accent_color(state.palette_t)

    # --- full-bleed background gradient (radial), always covers the frame ---
    bg = _background_array(view, width, height, base_color)
    img = Image.fromarray(bg, "RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    node_count = max(6, int(10 + state.signal_density * 90))
    nodes = _node_layout(state.scene_key, node_count)

    # --- pathway edges (connectivity) ---
    edge_alpha = int(40 + state.pathway_organization * 140)
    max_edge_dist = 0.05 + state.pathway_organization * 0.22
    edge_color = accent_color + (edge_alpha,)
    for i, (x1, y1, w1) in enumerate(nodes):
        for x2, y2, w2 in nodes[i + 1:i + 6]:
            dist = math.hypot(x2 - x1, y2 - y1)
            if dist < max_edge_dist:
                px1 = view.to_px(x1, y1, width, height)
                px2 = view.to_px(x2, y2, width, height)
                draw.line([px1, px2], fill=edge_color, width=max(1, int(1 + state.pathway_organization * 2)))

    # --- nodes (signal density / evidence intensity) ---
    for x, y, weight in nodes:
        px, py = view.to_px(x, y, width, height)
        r = (0.006 + weight * 0.014) * (0.6 + state.evidence_intensity * 0.8)
        r_px = max(1.0, view.scale_px(r, width))
        pulse = 1.0 + 0.15 * math.sin(state.frame / 8.0 + weight * 10)
        r_px *= pulse
        node_color = base_color if weight < 0.7 else accent_color
        draw.ellipse([px - r_px, py - r_px, px + r_px, py + r_px], fill=node_color + (230,))

    # --- central core (organism_maturity / structural_stability / central_geometry) ---
    core_r_world = 0.03 + state.organism_maturity * 0.10
    core_px = view.to_px(0.5, 0.5, width, height)
    core_r_px = max(2.0, view.scale_px(core_r_world, width))
    sides = 3 + int(state.central_geometry * 9)  # triangle -> 12-gon as geometry organizes
    _draw_polygon(draw, core_px, core_r_px, sides, state.structural_stability, accent_color, state.frame)

    # --- scene-specific accent motif ---
    _draw_scene_motif(draw, state, view, width, height, accent_color, base_color)

    return img


def _draw_polygon(draw, center, radius, sides, jitter_amount, color, frame):
    cx, cy = center
    rng = random.Random(SEED_BASE + frame // 24)  # stable within a second, changes every second
    points = []
    for i in range(sides):
        angle = (2 * math.pi * i / sides) - math.pi / 2 + frame * 0.004
        jitter = 1.0 + (rng.uniform(-0.06, 0.06) * (1.0 - jitter_amount))
        r = radius * jitter
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, outline=color + (255,), width=max(1, int(radius * 0.05)))
    draw.polygon(points, fill=color + (60,))


def _draw_scene_motif(draw, state, view, width, height, accent, base):
    key = state.scene_key
    if key == "coordinated_construction":
        # small rectilinear "blueprint" marks around the core -- construction
        rng = random.Random(SEED_BASE + 5)
        for _ in range(int(6 + state.pathway_organization * 10)):
            x = 0.5 + rng.uniform(-0.18, 0.18)
            y = 0.5 + rng.uniform(-0.18, 0.18)
            size = rng.uniform(0.01, 0.03)
            px, py = view.to_px(x, y, width, height)
            s_px = view.scale_px(size, width)
            draw.rectangle([px - s_px, py - s_px, px + s_px, py + s_px], outline=accent + (180,))
    elif key == "reality_testing":
        # scan lines sweeping -- validation stress
        sweep = (state.scene_progress * 1.6) % 1.0
        y = 0.5 - view.half_h + sweep * 2 * view.half_h
        x0, _ = view.to_px(view.cx - view.half_w, y, width, height)
        x1, _ = view.to_px(view.cx + view.half_w, y, width, height)
        _, y_px = view.to_px(0, y, width, height)
        draw.line([(x0, y_px), (x1, y_px)], fill=accent + (140,), width=2)
    elif key == "external_release":
        # radiating release lines from the core
        cx, cy = view.to_px(0.5, 0.5, width, height)
        n = 10
        length = view.scale_px(0.10 + state.release_readiness * 0.20, width)
        for i in range(n):
            angle = (2 * math.pi * i / n) + state.frame * 0.01
            x2 = cx + length * math.cos(angle)
            y2 = cy + length * math.sin(angle)
            draw.line([(cx, cy), (x2, y2)], fill=accent + (120,), width=2)
    elif key == "recursive_learning":
        # inward spiral -- retained memory feeding back
        cx, cy = view.to_px(0.5, 0.5, width, height)
        pts = []
        turns = 2.5
        n = 60
        for i in range(n):
            t = i / n
            angle = t * turns * 2 * math.pi
            r = view.scale_px(0.20 * (1 - t) * (0.5 + state.memory_depth), width)
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        draw.line(pts, fill=accent + (200,), width=2)


def frame_checksum(img: Image.Image) -> str:
    return hashlib.sha256(img.tobytes()).hexdigest()
