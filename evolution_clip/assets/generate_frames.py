#!/usr/bin/env python3
"""ForgeWorld Evolution Clip — scene frame generator.

Renders one 1080x1920 PNG per scene defined in scenes.json into
evolution_clip/frames/. Pure Pillow, no network calls, no external
image assets — every visual is drawn from repo-sourced text so
provenance stays traceable back to real ForgeWorld files (see
scenes.json "source_files" per scene and MANIFEST.md after render).

Termux note: requires `python-pillow` (pkg install python python-pillow).
"""
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent
CLIP_DIR = ASSETS_DIR.parent
REPO_ROOT = CLIP_DIR.parent
FRAMES_DIR = CLIP_DIR / "frames"

FONT_DIR = Path("/usr/share/fonts/truetype")
FONT_DISPLAY_BOLD = FONT_DIR / "dejavu/DejaVuSans-Bold.ttf"
FONT_DISPLAY = FONT_DIR / "dejavu/DejaVuSans.ttf"
FONT_MONO = FONT_DIR / "liberation/LiberationMono-Regular.ttf"
FONT_MONO_BOLD = FONT_DIR / "liberation/LiberationMono-Bold.ttf"


def font(path, size):
    return ImageFont.truetype(str(path), size)


def hexrgb(h, alpha=255):
    h = h.lstrip("#")
    if len(h) == 8:
        r, g, b, a = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, a)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (r, g, b, alpha)


def load_scenes():
    with open(ASSETS_DIR / "scenes.json") as f:
        return json.load(f)


def base_canvas(cfg):
    w, h = cfg["canvas"]["width"], cfg["canvas"]["height"]
    top = hexrgb(cfg["palette"]["bg_top"])
    bottom = hexrgb(cfg["palette"]["bg_bottom"])

    img = Image.new("RGB", (w, h), top[:3])
    px = img.load()
    for y in range(h):
        t = y / h
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(0, w, 4):
            for dx in range(4):
                if x + dx < w:
                    px[x + dx, y] = (r, g, b)

    # faint hairline grid — "system diagram" texture, restrained.
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    grid_color = hexrgb(cfg["palette"]["grid_line"])
    step = 80
    for x in range(0, w, step):
        gdraw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, step):
        gdraw.line([(0, y), (w, y)], fill=grid_color, width=1)
    img = Image.alpha_composite(img.convert("RGBA"), grid)

    # vignette
    vign = Image.new("L", (w, h), 0)
    vdraw = ImageDraw.Draw(vign)
    vdraw.ellipse([-w * 0.35, -h * 0.15, w * 1.35, h * 1.15], fill=90)
    vign = vign.filter(ImageFilter.GaussianBlur(220))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img = Image.composite(img, dark, vign)

    return img.convert("RGB")


def draw_centered_text(draw, cx, y, text, fnt, fill, spacing=8, anchor_top=True):
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = cx - tw / 2
    yy = y if anchor_top else y - th
    draw.text((x, yy), text, font=fnt, fill=fill)
    return th + spacing


def wrap_and_draw(draw, cx, y, text, fnt, fill, max_width_chars, line_gap=14):
    lines = textwrap.wrap(text, width=max_width_chars)
    yy = y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=fnt)
        th = bbox[3] - bbox[1]
        draw_centered_text(draw, cx, yy, line, fnt, fill, spacing=0)
        yy += th + line_gap
    return yy


def scene_label(draw, cx, y, label, gold):
    f = font(FONT_MONO_BOLD, 34)
    text = f"// {label}"
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw / 2, y), text, font=f, fill=gold)
    return y + (bbox[3] - bbox[1]) + 30


def render_narrative(draw, cfg, scene, w, h):
    gold = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    f = font(FONT_DISPLAY, 60)
    wrap_and_draw(draw, w / 2, h * 0.38, scene["text"], f, white, max_width_chars=17, line_gap=20)
    draw.line([(w / 2 - 60, h * 0.62), (w / 2 + 60, h * 0.62)], fill=gold, width=3)


def render_fragments(draw, cfg, scene, w, h):
    gold = hexrgb(cfg["palette"]["gold"])
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    y = scene_label(draw, w / 2, h * 0.10, scene["label"], gold_bright)
    f_head = font(FONT_DISPLAY_BOLD, 58)
    wrap_and_draw(draw, w / 2, y + 10, scene["label"], f_head, white, max_width_chars=14, line_gap=10)

    fm = font(FONT_MONO, 30)
    frags = scene["fragments"]
    start_y = h * 0.44
    row_h = 66
    import random
    rnd = random.Random(scene["id"])
    for i, frag in enumerate(frags):
        jitter_x = rnd.randint(-70, 70)
        yy = start_y + i * row_h
        c = dim if i % 3 == 0 else white
        draw.text((w / 2 - 300 + jitter_x, yy), f"~/{frag}", font=fm, fill=c)
    draw.text((w / 2 - 220, h * 0.90), "no shared schema. no shared memory.", font=font(FONT_MONO, 26), fill=dim)


def render_evidence(draw, cfg, scene, w, h):
    gold = hexrgb(cfg["palette"]["gold"])
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    y = scene_label(draw, w / 2, h * 0.10, scene["label"], gold_bright)
    f_head = font(FONT_DISPLAY_BOLD, 64)
    y = h * 0.10 + 90
    wrap_and_draw(draw, w / 2, y, scene["label"], f_head, white, max_width_chars=14, line_gap=10)

    f_quote = font(FONT_DISPLAY, 42)
    y2 = h * 0.40
    y2 = wrap_and_draw(draw, w / 2, y2, f'"{scene["quote"]}"', f_quote, gold_bright, max_width_chars=24, line_gap=14)

    f_cite = font(FONT_MONO, 24)
    draw_centered_text(draw, w / 2, y2 + 20, scene["citation"], f_cite, dim)

    fm = font(FONT_MONO, 26)
    ty = h * 0.68
    for i, step in enumerate(scene["trail"]):
        label = step if "/" in step or "." in step else step
        text = f"{i+1:02d}  {label}"
        draw_centered_text(draw, w / 2, ty, text, fm, white)
        ty += 42


def render_chain(draw, cfg, scene, w, h):
    gold = hexrgb(cfg["palette"]["gold"])
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    y = scene_label(draw, w / 2, h * 0.09, scene["label"], gold_bright)
    f_head = font(FONT_DISPLAY_BOLD, 64)
    wrap_and_draw(draw, w / 2, h * 0.09 + 90, scene["label"], f_head, white, max_width_chars=14, line_gap=10)

    fm = font(FONT_MONO_BOLD, 30)
    chain = scene["chain"]
    y = h * 0.36
    step_h = (h * 0.82 - y) / len(chain)
    for i, node in enumerate(chain):
        yy = y + i * step_h
        col = gold_bright if i in (0, len(chain) - 1) else white
        draw_centered_text(draw, w / 2, yy, node, fm, col)
        if i < len(chain) - 1:
            arrow_y = yy + 34
            draw.text((w / 2 - 6, arrow_y), "|", font=fm, fill=dim)

    draw_centered_text(draw, w / 2, h * 0.90, scene["citation"], font(FONT_MONO, 22), dim)


def render_orchestration(draw, cfg, scene, w, h):
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    y = scene_label(draw, w / 2, h * 0.10, scene["label"], gold_bright)
    f_head = font(FONT_DISPLAY_BOLD, 62)
    wrap_and_draw(draw, w / 2, h * 0.10 + 90, scene["label"], f_head, white, max_width_chars=14, line_gap=10)

    f_quote = font(FONT_DISPLAY, 38)
    y2 = wrap_and_draw(draw, w / 2, h * 0.37, f'"{scene["quote"]}"', f_quote, gold_bright, max_width_chars=26, line_gap=12)

    fm_h = font(FONT_MONO_BOLD, 26)
    fm = font(FONT_MONO, 24)
    left_x = w * 0.28
    right_x = w * 0.72
    ty = h * 0.60
    for side, cx in (("detail_left", left_x), ("detail_right", right_x)):
        lines = scene[side].split("\n")
        yy = ty
        for i, line in enumerate(lines):
            fnt = fm_h if i == 0 else fm
            col = gold_bright if i == 0 else white
            bbox = draw.textbbox((0, 0), line, font=fnt)
            tw = bbox[2] - bbox[0]
            draw.text((cx - tw / 2, yy), line, font=fnt, fill=col)
            yy += (bbox[3] - bbox[1]) + 16

    draw.line([(w / 2, h * 0.58), (w / 2, h * 0.86)], fill=dim, width=1)
    draw_centered_text(draw, w / 2, h * 0.92, scene["citation"], font(FONT_MONO, 22), dim)


def render_capability_grid(draw, cfg, scene, w, h):
    gold = hexrgb(cfg["palette"]["gold"])
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    y = scene_label(draw, w / 2, h * 0.09, scene["label"], gold_bright)
    f_head = font(FONT_DISPLAY_BOLD, 62)
    wrap_and_draw(draw, w / 2, h * 0.09 + 90, scene["label"], f_head, white, max_width_chars=14, line_gap=10)

    nodes = scene["nodes"]
    cols = 3
    rows = (len(nodes) + cols - 1) // cols
    grid_top = h * 0.36
    grid_bottom = h * 0.84
    cell_w = w / cols
    cell_h = (grid_bottom - grid_top) / rows
    fm = font(FONT_MONO, 22)
    r = 10
    cx0 = w / 2
    positions = []
    for i, node in enumerate(nodes):
        col = i % cols
        row = i // cols
        cx = cell_w * col + cell_w / 2
        cy = grid_top + cell_h * row + cell_h / 2
        positions.append((cx, cy))

    for cx, cy in positions:
        draw.line([(cx0, grid_top - 40), (cx, cy)], fill=hexrgb(cfg["palette"]["grid_line"]), width=1)

    for (cx, cy), node in zip(positions, nodes):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=gold_bright, width=2, fill=hexrgb(cfg["palette"]["bg_bottom"]))
        bbox = draw.textbbox((0, 0), node, font=fm)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw / 2, cy + 18), node, font=fm, fill=white)

    draw.ellipse([cx0 - 14, grid_top - 54, cx0 + 14, grid_top - 26], fill=gold_bright)
    draw_centered_text(draw, w / 2, h * 0.92, scene["citation"], font(FONT_MONO, 22), dim)


def render_word_beat(draw, cfg, scene, w, h):
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    f = font(FONT_DISPLAY_BOLD, 108)
    draw_centered_text(draw, w / 2, h * 0.46, scene["word"], f, white, anchor_top=False)
    draw.line([(w / 2 - 50, h * 0.50), (w / 2 + 50, h * 0.50)], fill=gold_bright, width=3)
    draw_centered_text(draw, w / 2, h * 0.55, scene["sub"], font(FONT_MONO, 24), dim)


def render_closing(draw, cfg, scene, w, h):
    gold_bright = hexrgb(cfg["palette"]["gold_bright"])
    white = hexrgb(cfg["palette"]["white"])
    dim = hexrgb(cfg["palette"]["dim"])

    f_title = font(FONT_DISPLAY_BOLD, 96)
    draw_centered_text(draw, w / 2, h * 0.40, scene["title"], f_title, gold_bright, anchor_top=False)
    draw.line([(w / 2 - 90, h * 0.43), (w / 2 + 90, h * 0.43)], fill=gold_bright, width=2)
    f_sub = font(FONT_MONO, 30)
    draw_centered_text(draw, w / 2, h * 0.47, scene["subtitle"], f_sub, white)

    f_line = font(FONT_DISPLAY, 38)
    wrap_and_draw(draw, w / 2, h * 0.60, scene["line"], f_line, white, max_width_chars=22, line_gap=14)


RENDERERS = {
    "narrative": render_narrative,
    "fragments": render_fragments,
    "evidence": render_evidence,
    "chain": render_chain,
    "orchestration": render_orchestration,
    "capability_grid": render_capability_grid,
    "word_beat": render_word_beat,
    "closing": render_closing,
}


def verify_source_files(scene):
    missing = []
    for rel in scene.get("source_files", []):
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)
    return missing


def main():
    cfg = load_scenes()
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    w, h = cfg["canvas"]["width"], cfg["canvas"]["height"]

    manifest_rows = []
    all_missing = {}

    for scene in cfg["scenes"]:
        missing = verify_source_files(scene)
        if missing:
            all_missing[scene["id"]] = missing

        img = base_canvas(cfg)
        draw = ImageDraw.Draw(img)
        renderer = RENDERERS[scene["kind"]]
        renderer(draw, cfg, scene, w, h)

        out_path = FRAMES_DIR / f"{scene['id']}.png"
        img.save(out_path, "PNG")
        manifest_rows.append({
            "id": scene["id"],
            "kind": scene["kind"],
            "duration": scene["duration"],
            "frame": str(out_path.relative_to(REPO_ROOT)),
            "source_files": scene.get("source_files", []),
        })
        print(f"rendered {out_path.name}  ({scene['duration']}s, {scene['kind']})")

    (CLIP_DIR / "output").mkdir(parents=True, exist_ok=True)
    with open(CLIP_DIR / "output" / "frame_manifest.json", "w") as f:
        json.dump({"scenes": manifest_rows, "crossfade_sec": cfg["crossfade_sec"]}, f, indent=2)

    if all_missing:
        print("\nWARNING: some declared source_files do not exist on disk:")
        for sid, files in all_missing.items():
            print(f"  {sid}: {files}")
    else:
        print("\nAll declared source_files verified present in repo.")


if __name__ == "__main__":
    main()
