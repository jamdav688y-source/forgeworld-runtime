#!/usr/bin/env python3
"""ForgeWorld Evolution Clip renderer.

Smallest-equivalent implementation of the described pipeline:
    scenes.json -> Pillow frame generation -> FFmpeg assembly ->
    preview -> visual validation -> 1080x1920 final -> provenance manifest.

Each scene in scenes.json is rendered as ONE static 1080x1920 PNG frame by a
dedicated layout function selected on the scene's "type" field. FFmpeg then
assembles the sequence into an MP4, holding each frame for its declared
duration_s and cross-fading between adjacent scenes. No larger video
framework (no timeline editor, no animation engine) is introduced.

Usage:
    render.py <scenes.json> <output_dir> [--preview-only] [--fps 24]
"""
import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
F_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
F_REG = FONT_DIR / "DejaVuSans.ttf"
F_MONO = FONT_DIR / "DejaVuSansMono.ttf"
F_MONO_BOLD = FONT_DIR / "DejaVuSansMono-Bold.ttf"

BG = (9, 12, 18)
PANEL = (19, 25, 35)
PANEL_BORDER = (40, 50, 64)
TEXT_PRIMARY = (232, 238, 244)
TEXT_SECONDARY = (146, 160, 178)
TEXT_DIM = (96, 108, 124)
ACCENT_TEAL = (72, 216, 200)
ACCENT_AMBER = (240, 175, 70)
SOURCE_FACT = (96, 176, 244)
INTERPRETATION = (240, 175, 70)
PASS_C = (76, 205, 130)
PARTIAL_C = (236, 180, 60)
FAIL_C = (232, 90, 90)
NOTTESTED_C = (120, 132, 148)

VERDICT_COLORS = {"PASS": PASS_C, "PARTIAL": PARTIAL_C, "FAIL": FAIL_C, "NOT TESTED": NOTTESTED_C}


def font(path, size):
    return ImageFont.truetype(str(path), size)


_MEASURE_IMG = Image.new("RGB", (1, 1))
_MEASURE_DRAW = ImageDraw.Draw(_MEASURE_IMG)


def wrap_draw(draw, xy, text, fnt, fill, max_width, line_spacing=1.3, measure_only=False):
    x, y = xy
    meter = _MEASURE_DRAW if measure_only or draw is None else draw
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if meter.textlength(trial, font=fnt) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    bbox = fnt.getbbox("Ag")
    lh = int((bbox[3] - bbox[1]) * line_spacing) + 8
    if not measure_only and draw is not None:
        for i, line in enumerate(lines):
            draw.text((x, y + i * lh), line, font=fnt, fill=fill)
    return y + len(lines) * lh


def rounded_panel(draw, box, radius=22, fill=PANEL, outline=PANEL_BORDER, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def base_canvas():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for i in range(H):
        t = i / H
        c = tuple(int(BG[k] + (14 - BG[k]) * (t * 0.35)) for k in range(3))
        d.line([(0, i), (W, i)], fill=c)
    return img, d


def draw_kicker(d, text, y=120):
    f = font(F_MONO_BOLD, 30)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y), text, font=f, fill=ACCENT_TEAL)


def draw_footer(d, text="FORGEWORLD VALIDATION 001", y=None):
    f = font(F_MONO, 24)
    if y is None:
        y = H - 70
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y), text, font=f, fill=TEXT_DIM)


def chip(d, xy, label, color):
    f = font(F_MONO_BOLD, 22)
    pad_x, pad_y = 16, 8
    tw = d.textlength(label, font=f)
    x, y = xy
    box = [x, y, x + tw + pad_x * 2, y + 30 + pad_y]
    d.rounded_rectangle(box, radius=8, outline=color, width=2)
    d.text((x + pad_x, y + pad_y - 2), label, font=f, fill=color)
    return box[2] - box[0]


# ---------- scene layouts ----------

def scene_title(s):
    img, d = base_canvas()
    draw_kicker(d, s.get("kicker", "SCENE 1 — THE QUESTION"), 150)
    f_title = font(F_BOLD, 74)
    y = 320
    for line in s["title_lines"]:
        tw = d.textlength(line, font=f_title)
        d.text(((W - tw) / 2, y), line, font=f_title, fill=TEXT_PRIMARY)
        y += 92

    f_sub = font(F_REG, 40)
    y += 40
    wrapped_y = y
    sub_lines = textwrap.wrap(s["subtitle"], width=26)
    for line in sub_lines:
        tw = d.textlength(line, font=f_sub)
        d.text(((W - tw) / 2, wrapped_y), line, font=f_sub, fill=ACCENT_AMBER)
        wrapped_y += 56

    # dimmed screenshot preview behind a panel, lower half
    if s.get("screenshot_crop"):
        shot = Image.open(s["screenshot_path"]).convert("RGB")
        crop = shot.crop(s["screenshot_crop"])
        target_w = 760
        ratio = target_w / crop.width
        crop = crop.resize((target_w, int(crop.height * ratio)))
        crop = crop.crop((0, 0, crop.width, min(crop.height, 620)))
        overlay = Image.new("RGB", crop.size, (0, 0, 0))
        crop = Image.blend(crop, overlay, 0.30)
        px = (W - crop.width) // 2
        py = 980
        rounded_panel(d, [px - 18, py - 18, px + crop.width + 18, py + crop.height + 18], radius=26)
        img.paste(crop, (px, py))
        d.rectangle([px, py, px + crop.width, py + crop.height], outline=PANEL_BORDER, width=2)
        cap_f = font(F_MONO, 24)
        cap = "actual external exchange (unedited)"
        tw = d.textlength(cap, font=cap_f)
        d.text(((W - tw) / 2, py + crop.height + 34), cap, font=cap_f, fill=TEXT_DIM)

    draw_footer(d)
    return img


def scene_source(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 2 — SOURCE", 100)
    f_h = font(F_BOLD, 56)
    tw = d.textlength(s["heading"], font=f_h)
    d.text(((W - tw) / 2, 170), s["heading"], font=f_h, fill=TEXT_PRIMARY)
    f_sub = font(F_REG, 32)
    tw = d.textlength(s["subheading"], font=f_sub)
    d.text(((W - tw) / 2, 250), s["subheading"], font=f_sub, fill=TEXT_SECONDARY)

    shot = Image.open(s["screenshot_path"]).convert("RGB")
    crop = shot.crop(s["screenshot_crop"])
    target_w = 860
    ratio = target_w / crop.width
    crop = crop.resize((target_w, int(crop.height * ratio)))
    px = (W - crop.width) // 2
    py = 320
    rounded_panel(d, [px - 16, py - 16, px + crop.width + 16, py + crop.height + 16], radius=24)
    img.paste(crop, (px, py))

    panel_top = py + crop.height + 50
    f_k = font(F_MONO_BOLD, 30)
    f_v = font(F_MONO, 26)
    fields = s["fields"]

    # Dry-run field layout to size the panel to its actual content.
    def layout_fields(start_y):
        row_y = start_y
        for label, value in fields:
            row_y += 42
            end_y = wrap_draw(None, (110, row_y), value, f_v, TEXT_PRIMARY, W - 220, line_spacing=1.25, measure_only=True)
            row_y = end_y + 20
        return row_y

    content_end = layout_fields(panel_top + 40)
    panel_bottom = content_end + 20
    rounded_panel(d, [70, panel_top, W - 70, panel_bottom])
    row_y = panel_top + 40
    for label, value in fields:
        d.text((110, row_y), label, font=f_k, fill=ACCENT_TEAL)
        row_y += 42
        row_y = wrap_draw(d, (110, row_y), value, f_v, TEXT_PRIMARY, W - 220, line_spacing=1.25)
        row_y += 20

    note_f = font(F_REG, 24)
    wrap_draw(d, (70, panel_bottom + 34), s["footnote"], note_f, TEXT_DIM, W - 140, line_spacing=1.25)

    draw_footer(d)
    return img


def scene_extraction(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 3 — EXTRACTION", 100)
    f_h = font(F_BOLD, 52)
    tw = d.textlength(s["heading"], font=f_h)
    d.text(((W - tw) / 2, 170), s["heading"], font=f_h, fill=TEXT_PRIMARY)

    y = 300
    for block in s["blocks"]:
        rounded_panel(d, [70, y, W - 70, y + block["height"]])
        f_lbl = font(F_MONO_BOLD, 30)
        d.text((110, y + 30), block["label"], font=f_lbl, fill=ACCENT_AMBER)
        chip(d, (W - 70 - 230, y + 26), block["classification"], INTERPRETATION if "INTERPRETATION" in block["classification"] else SOURCE_FACT)
        f_body = font(F_REG, 30)
        wrap_draw(d, (110, y + 90), block["text"], f_body, TEXT_PRIMARY, W - 220, line_spacing=1.3)
        f_note = font(F_REG, 22)
        wrap_draw(d, (110, y + block["height"] - 70), block["note"], f_note, TEXT_DIM, W - 220, line_spacing=1.2)
        y += block["height"] + 40

    draw_footer(d)
    return img


def draw_flow_chain(d, items, x_center, y_start, box_w=700, box_h=110, gap=54, fnt_size=30, colors=None):
    f = font(F_MONO_BOLD, fnt_size)
    y = y_start
    for i, label in enumerate(items):
        color = (colors[i] if colors else PANEL_BORDER)
        box = [x_center - box_w / 2, y, x_center + box_w / 2, y + box_h]
        d.rounded_rectangle(box, radius=16, fill=PANEL, outline=color, width=3)
        tw = d.textlength(label, font=f)
        th = fnt_size
        d.text((x_center - tw / 2, y + (box_h - th) / 2 - 6), label, font=f, fill=TEXT_PRIMARY)
        if i < len(items) - 1:
            ax = x_center
            ay0 = y + box_h
            ay1 = y + box_h + gap
            d.line([(ax, ay0 + 6), (ax, ay1 - 14)], fill=ACCENT_TEAL, width=4)
            d.polygon([(ax - 12, ay1 - 14), (ax + 12, ay1 - 14), (ax, ay1)], fill=ACCENT_TEAL)
        y += box_h + gap
    return y


def scene_governance(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 4 — GOVERNANCE", 100)
    f_h = font(F_BOLD, 50)
    tw = d.textlength(s["heading"], font=f_h)
    d.text(((W - tw) / 2, 170), s["heading"], font=f_h, fill=TEXT_PRIMARY)

    colors = [SOURCE_FACT, SOURCE_FACT, INTERPRETATION, ACCENT_TEAL]
    end_y = draw_flow_chain(d, s["chain"], W / 2, 320, colors=colors)

    legend_y = end_y + 30
    lx = 130
    chip(d, (lx, legend_y), "SOURCE FACT", SOURCE_FACT)
    chip(d, (lx + 330, legend_y), "FORGEWORLD INTERPRETATION", INTERPRETATION)

    f_note = font(F_REG, 28)
    wrap_draw(d, (90, legend_y + 80), s["note"], f_note, TEXT_SECONDARY, W - 180, line_spacing=1.3)

    draw_footer(d)
    return img


def scene_mission(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 5 — MISSION", 130)
    f_id = font(F_BOLD, 84)
    tw = d.textlength(s["mission_id"], font=f_id)
    d.text(((W - tw) / 2, 260), s["mission_id"], font=f_id, fill=ACCENT_TEAL)

    panel_top = 460
    rounded_panel(d, [90, panel_top, W - 90, panel_top + 520])
    f_lbl = font(F_MONO_BOLD, 32)
    d.text((130, panel_top + 40), "OBJECTIVE", font=f_lbl, fill=ACCENT_AMBER)
    f_body = font(F_REG, 34)
    wrap_draw(d, (130, panel_top + 100), s["objective"], f_body, TEXT_PRIMARY, W - 260, line_spacing=1.35)

    f_lbl2 = font(F_MONO_BOLD, 28)
    d.text((130, panel_top + 320), "GENERATED BY", font=f_lbl2, fill=ACCENT_AMBER)
    f_body2 = font(F_MONO, 24)
    wrap_draw(d, (130, panel_top + 366), s["generated_by"], f_body2, TEXT_SECONDARY, W - 260, line_spacing=1.3)

    draw_footer(d)
    return img


def scene_execution(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 6 — EXECUTION", 100)
    f_h = font(F_BOLD, 48)
    tw = d.textlength(s["heading"], font=f_h)
    d.text(((W - tw) / 2, 170), s["heading"], font=f_h, fill=TEXT_PRIMARY)

    steps = s["steps"]
    colors = [PASS_C if st["verdict"] == "PASS" else FAIL_C for st in steps]
    labels = [f"{st['name']}  ·  {st['verdict']}  ·  {st['duration']}" for st in steps]
    draw_flow_chain(d, labels, W / 2, 280, box_h=100, gap=30, fnt_size=24, colors=colors)

    f_note = font(F_REG, 26)
    y_note = 280 + len(steps) * 130 + 20
    wrap_draw(d, (90, y_note), s["note"], f_note, TEXT_DIM, W - 180, line_spacing=1.25)

    draw_footer(d)
    return img


def scene_trace(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 7 — TRACEABILITY TEST", 90)
    f_q = font(F_BOLD, 40)
    tw = d.textlength(s["question"], font=f_q)
    wrap_draw(d, (W / 2 - tw / 2 if tw < W - 100 else 90, 160), s["question"], f_q, ACCENT_AMBER, W - 180, line_spacing=1.25)

    end_y = draw_flow_chain(d, s["chain"], W / 2, 320, box_h=100, gap=36, fnt_size=26, colors=[ACCENT_TEAL] * len(s["chain"]))

    f_v = font(F_BOLD, 44)
    verdict = s["verdict"]
    color = VERDICT_COLORS.get(verdict, TEXT_PRIMARY)
    label = f"BACKWARD TRACE: {verdict}"
    tw = d.textlength(label, font=f_v)
    box = [W / 2 - tw / 2 - 30, end_y + 30, W / 2 + tw / 2 + 30, end_y + 30 + 90]
    d.rounded_rectangle(box, radius=18, outline=color, width=4)
    d.text((W / 2 - tw / 2, end_y + 30 + 22), label, font=f_v, fill=color)

    draw_footer(d)
    return img


def scene_metrics(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 8 — RESULT", 90)
    f_h = font(F_BOLD, 46)
    tw = d.textlength(s["heading"], font=f_h)
    d.text(((W - tw) / 2, 150), s["heading"], font=f_h, fill=TEXT_PRIMARY)

    y = 250
    row_h = 78
    f_name = font(F_REG, 27)
    f_v = font(F_MONO_BOLD, 24)
    for m in s["metrics"]:
        rounded_panel(d, [70, y, W - 70, y + row_h - 12], radius=14)
        wrap_draw(d, (100, y + 20), m["name"], f_name, TEXT_PRIMARY, 620, line_spacing=1.1)
        color = VERDICT_COLORS.get(m["verdict"], TEXT_PRIMARY)
        chip(d, (W - 70 - 210, y + 14), m["verdict"], color)
        y += row_h

    draw_footer(d)
    return img


def scene_limitations(s):
    img, d = base_canvas()
    draw_kicker(d, "SCENE 9 — LIMITATIONS", 130)
    f_h = font(F_BOLD, 50)
    tw = d.textlength(s["heading"], font=f_h)
    d.text(((W - tw) / 2, 250), s["heading"], font=f_h, fill=TEXT_PRIMARY)

    y = 420
    f_item = font(F_REG, 34)
    for item in s["items"]:
        d.ellipse([100, y + 12, 116, y + 28], fill=ACCENT_AMBER)
        y2 = wrap_draw(d, (140, y), item, f_item, TEXT_SECONDARY, W - 240, line_spacing=1.3)
        y = y2 + 24

    draw_footer(d)
    return img


def scene_closing(s):
    img, d = base_canvas()
    f_title = font(F_BOLD, 60)
    y = 220
    for line in s["title_lines"]:
        tw = d.textlength(line, font=f_title)
        d.text(((W - tw) / 2, y), line, font=f_title, fill=TEXT_PRIMARY)
        y += 74

    y += 30
    f_line = font(F_REG, 38)
    for line in s["statement_lines"]:
        tw = d.textlength(line, font=f_line)
        d.text(((W - tw) / 2, y), line, font=f_line, fill=ACCENT_AMBER)
        y += 52

    y += 60
    end_y = draw_flow_chain(d, s["chain"], W / 2, y, box_w=780, box_h=88, gap=26, fnt_size=26, colors=[ACCENT_TEAL] * len(s["chain"]))

    y2 = end_y + 60
    f_logo = font(F_BOLD, 50)
    tw = d.textlength(s["logo"], font=f_logo)
    d.text(((W - tw) / 2, y2), s["logo"], font=f_logo, fill=TEXT_PRIMARY)
    f_tag = font(F_REG, 30)
    tw = d.textlength(s["tagline"], font=f_tag)
    d.text(((W - tw) / 2, y2 + 66), s["tagline"], font=f_tag, fill=TEXT_SECONDARY)

    return img


SCENE_RENDERERS = {
    "title": scene_title,
    "source": scene_source,
    "extraction": scene_extraction,
    "governance": scene_governance,
    "mission": scene_mission,
    "execution": scene_execution,
    "trace": scene_trace,
    "metrics": scene_metrics,
    "limitations": scene_limitations,
    "closing": scene_closing,
}


def render_scenes(scenes_path, out_dir):
    scenes = json.loads(Path(scenes_path).read_text())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, s in enumerate(scenes):
        fn = SCENE_RENDERERS[s["type"]]
        img = fn(s)
        frame_path = out_dir / f"scene_{i:02d}_{s['id']}.png"
        img.save(frame_path)
        manifest.append({"index": i, "id": s["id"], "type": s["type"], "duration_s": s["duration_s"], "frame": str(frame_path)})
    return manifest


def assemble_ffmpeg(manifest, output_mp4, fps=24, xfade_s=0.4):
    inputs = []
    filter_parts = []
    n = len(manifest)
    for m in manifest:
        inputs += ["-loop", "1", "-t", str(m["duration_s"] + (xfade_s if m is not manifest[-1] else 0)), "-i", m["frame"]]

    labels = [f"[{i}:v]" for i in range(n)]
    scaled = []
    for i in range(n):
        scaled.append(f"{labels[i]}scale={W}:{H},format=yuv420p[v{i}]")
    filter_parts.extend(scaled)

    cur = "v0"
    offset = manifest[0]["duration_s"] - xfade_s
    for i in range(1, n):
        nxt = f"vx{i}"
        filter_parts.append(f"[{cur}][v{i}]xfade=transition=fade:duration={xfade_s}:offset={offset:.3f}[{nxt}]")
        cur = nxt
        offset += manifest[i]["duration_s"] - xfade_s

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{cur}]",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-crf", "20",
        str(output_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes_json")
    ap.add_argument("out_dir")
    ap.add_argument("--mp4", default=None)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--frames-only", action="store_true")
    args = ap.parse_args()

    manifest = render_scenes(args.scenes_json, args.out_dir)
    print(json.dumps(manifest, indent=2))

    if not args.frames_only and args.mp4:
        proc = assemble_ffmpeg(manifest, args.mp4, fps=args.fps)
        if proc.returncode != 0:
            print("FFMPEG FAILED", file=sys.stderr)
            print(proc.stderr[-4000:], file=sys.stderr)
            sys.exit(1)
        print(f"Wrote {args.mp4}")


if __name__ == "__main__":
    main()
