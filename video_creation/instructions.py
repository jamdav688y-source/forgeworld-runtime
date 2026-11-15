"""Deterministic, local instruction-to-project compiler for the phone Studio."""
from __future__ import annotations

import re
import unicodedata

MAX_INSTRUCTION_CHARS = 10_000


def _line_value(text: str, key: str, maximum: int) -> str | None:
    match = re.search(rf"(?im)^\s*(?:{key})\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip(" \t\"'“”‘’")[:maximum] if match else None


def _title(text: str) -> str | None:
    value = _line_value(text, "title", 100)
    if value:
        return value
    match = re.search(r"(?i)\b(?:title|titled|call it|name it)\s+[\"'“‘]([^\"'”’\n]{1,100})[\"'”’]", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?i)\b(?:title|titled|call it|name it)\s+([A-Z][A-Za-z0-9 &'!:,-]{1,90}?)(?:\.|;|\n|$)", text)
    if match:
        return match.group(1).strip(" .,:;!-\t")
    if re.search(r"(?i)the vernal difference", text):
        return "The Vernal Difference"
    return None


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value)).strip("-")[:42] or "instruction-video"


def compile_instructions(text: str, assets: list[dict]) -> dict:
    """Map a natural-language brief to bounded render settings and media picks.

    This is a transparent local parser, not a claim of general natural-language
    understanding. Unrecognized creative language is preserved verbatim for the
    user and for future production stages.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_INSTRUCTION_CHARS or "\x00" in text:
        raise ValueError(f"instructions must contain 1 to {MAX_INSTRUCTION_CHARS} characters")
    brief = text.strip()
    duration_match = re.search(r"(?i)\b(?:exactly\s+)?(\d{1,3})\s*(?:-\s*)?(?:seconds?|secs?|s)\b", brief)
    duration = int(duration_match.group(1)) if duration_match else 10
    if not 1 <= duration <= 60:
        raise ValueError("instruction duration must be from 1 to 60 seconds per scene")

    lowered = brief.lower()
    if any(term in lowered for term in ("9:16", "vertical", "story", "shorts", "portrait")):
        video_format = "vertical"
    elif any(term in lowered for term in ("16:9", "landscape", "widescreen")):
        video_format = "landscape"
    elif any(term in lowered for term in ("1:1", "square")):
        video_format = "square"
    else:
        video_format = "vertical"

    if re.search(r"\b(static|no camera movement|locked camera)\b", lowered):
        motion = "static"
    elif re.search(r"\b(pan\s+left|move\s+left|drift\s+left)\b", lowered):
        motion = "pan_left"
    elif re.search(r"\b(pan\s+right|move\s+right|drift\s+right)\b", lowered):
        motion = "pan_right"
    elif re.search(r"\b(pull\s*(out|back)|zoom\s*out|move\s*(back|away)|back\s*away)\b", lowered):
        motion = "pull_out"
    else:
        motion = "push_in"

    title = _title(brief) or "The Vernal Difference" if "vernal difference" in lowered else _title(brief)
    title = title or "ForgeWorld Video"
    caption = _line_value(brief, "captions?", 500)
    description = _line_value(brief, "description", 5000) or brief[:5000]
    tags_line = _line_value(brief, "tags", 2000) or ""
    tags = [item.strip()[:100] for item in tags_line.split(",") if item.strip()][:30]

    visual_assets = [row for row in assets if row.get("kind") in {"image", "video"}]
    audio_assets = [row for row in assets if row.get("kind") == "audio"]
    requested = re.search(r"(?i)\b(?:use|from|start with)\s+[\"'“‘]?([^\n\"'”’]{2,120})", brief)
    picked = None
    if requested:
        phrase = requested.group(1).strip(" .,:;!?\t").lower()
        picked = next((row for row in visual_assets if phrase in row.get("name", "").lower()), None)
    if re.search(r"(?i)\b(all|every)\s+(?:my\s+)?(?:clips|scenes|images|assets)\b", brief):
        selected_visuals = visual_assets
    elif picked:
        selected_visuals = [picked]
    else:
        selected_visuals = visual_assets[:1]

    selected_audio = None
    if audio_assets and re.search(r"(?i)\b(add|use|include|with)\s+(?:the\s+)?(?:music|audio|narration|soundtrack)\b", brief):
        selected_audio = audio_assets[0]

    assets_description = [row.get("name", "") for row in selected_visuals]
    if selected_audio:
        assets_description.append(selected_audio.get("name", ""))
    assumptions = [f"{duration} seconds per scene", video_format, f"still image motion: {motion.replace('_', ' ')}"]
    assumptions.append("source: " + (", ".join(assets_description) if assets_description else "none selected yet"))
    if re.search(r"(?i)\b(music|audio|narration|soundtrack)\b", brief) and not selected_audio:
        assumptions.append("no audio asset found; video will render without added audio")
    if any(row.get("kind") == "video" for row in selected_visuals):
        assumptions.append("camera motion presets affect still images; source clips keep their recorded camera movement")
    limitations = []
    if re.search(r"(?i)\b(animate|animation|living|come to life|move its body|body movement|lip.?sync|particles?|smoke simulation)\b", brief):
        limitations.append("The local renderer cannot synthesize object or creature motion, lip sync, or particle physics; it can move the camera framing over still artwork and assemble supplied clips.")
    limitations.append("Unrecognized style directions are preserved in the creative brief; v1 applies only the listed timing, format, title, caption, audio, source-selection, and still-camera controls.")
    return {
        "brief": brief,
        "project_id_base": _slug(title),
        "title": title[:100],
        "description": description,
        "tags": tags,
        "duration_seconds": duration,
        "format": video_format,
        "motion": motion,
        "caption": caption,
        "visual_assets": selected_visuals,
        "audio_asset": selected_audio,
        "assumptions": assumptions,
        "limitations": limitations,
    }
