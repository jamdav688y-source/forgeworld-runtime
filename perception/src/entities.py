"""ENTITY EXTRACTION stage: deterministic, rule-based, over OCR text only.

Same posture as whatsapp/src/classify.py's keyword-list classifier: no NER
model or AI-routing credentials are wired for this channel, so entity
extraction here is a small, auditable heuristic -- not a claim of general
entity-recognition capability. Every entity signal traces back to the exact
OCR signal it was read from (both the observation and the OCR signal id are
recorded in evidence_references) so a wrong guess is traceable to a specific
extraction, not "the pipeline."

Two entity_types are extracted, matching the acceptance test verbatim
("OCR extracts recognizable platform names and visible page titles"):
  platform_name -- a known platform string appearing in the OCR text
  page_title    -- the longest line of OCR text, on the theory that a
                    screenshot's page/app title is usually its most
                    prominent (and thus often longest contiguous) line;
                    deliberately simple, documented as a heuristic.
"""
import re

from . import schema

KNOWN_PLATFORMS = [
    "WhatsApp", "GitHub", "YouTube", "Instagram", "Facebook", "Twitter", "X",
    "LinkedIn", "TikTok", "Reddit", "Telegram", "Signal", "Discord", "Slack",
    "Gmail", "Google", "Amazon", "Netflix", "Spotify", "Pocket Cortex",
    "ForgeWorld", "Chrome", "Termux",
]


def _find_platform_names(text: str) -> list:
    """Word-boundary matching, not naive substring containment -- a short
    platform name like "X" must not match inside an unrelated word (e.g.
    "Cortex"). \b works here because every entry in KNOWN_PLATFORMS is
    alphanumeric-plus-space, so re.escape + \b boundaries behave as
    expected on both ends."""
    found = []
    for platform in KNOWN_PLATFORMS:
        pattern = r"\b" + re.escape(platform) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(platform)
    return found


def _find_page_title(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    return max(lines, key=len)


def extract_entities(observation: dict, ocr_signal: dict) -> list:
    """Returns a list of ExtractedSignal (signal_type='entity'), one per
    recognized platform name plus one for the page title, if any text was
    extracted at all. Returns [] for empty OCR text -- no entity is
    fabricated from nothing."""
    text = ocr_signal.get("value") or ""
    if not text.strip():
        return []

    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]
    signals = []

    for platform in _find_platform_names(text):
        sig = schema.new_extracted_signal(
            image_id=image_id, image_sha256=image_sha256, signal_type="entity",
            value={"entity_type": "platform_name", "text": platform},
            extraction_method="keyword_match", provider=None,
            confidence=1.0,  # exact substring match against a known list, not a probabilistic guess
            observation_id=observation["id"],
        )
        sig["evidence_references"] = [observation["id"], ocr_signal["id"]]
        errors = schema.validate_extracted_signal(sig)
        if errors:
            raise ValueError(f"entity ExtractedSignal failed validation: {errors}")
        signals.append(sig)

    title = _find_page_title(text)
    if title:
        sig = schema.new_extracted_signal(
            image_id=image_id, image_sha256=image_sha256, signal_type="entity",
            value={"entity_type": "page_title", "text": title},
            extraction_method="longest_line_heuristic", provider=None,
            confidence=0.6,  # a heuristic, not a verified title -- deliberately below 1.0
            observation_id=observation["id"],
        )
        sig["evidence_references"] = [observation["id"], ocr_signal["id"]]
        errors = schema.validate_extracted_signal(sig)
        if errors:
            raise ValueError(f"entity ExtractedSignal failed validation: {errors}")
        signals.append(sig)

    return signals
