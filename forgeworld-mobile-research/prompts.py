"""Structured, source-grounded prompt construction.

Every generated prompt must separate SOURCE-DERIVED CONTENT from OPERATOR
NOTES, SYSTEM INFERENCE, and UNKNOWN INFORMATION, and must never claim it
was sent externally -- the operator decides what to do with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import load_prompt_templates
from database import Database, utcnow

VALID_MODES = [
    "SUMMARIZE_SOURCES",
    "COMPARE_ARCHITECTURES",
    "EXTRACT_MECHANISMS",
    "IDENTIFY_CONTRADICTIONS",
    "CREATE_CODEX_DIRECTIVE",
    "CREATE_CLAUDE_CODE_DIRECTIVE",
    "CREATE_CHATGPT_DIRECTIVE",
    "CREATE_LINKEDIN_COMMENT",
    "CREATE_LINKEDIN_POST",
    "CREATE_CINEMA_BRIEF",
    "CREATE_RPG_MECHANIC",
    "CREATE_RESEARCH_QUESTIONS",
    "CREATE_NOTEBOOKLM_SOURCE_BRIEF",
    "CREATE_COMMERCIAL_PROOF_BRIEF",
    "CREATE_CUSTOMER_DEMONSTRATION_BRIEF",
]


@dataclass
class SourceInventoryItem:
    screenshot_id: int
    sha256: str
    original_path: str
    title: str | None
    ocr_excerpt: str
    corrected_ocr_excerpt: str | None
    tags: list[str]
    entities: list[str]
    operator_notes: list[str]
    system_summary: str | None
    ocr_confidence: float | None
    classification_confidence: float | None
    processing_status: str
    uncertainty: list[str] = field(default_factory=list)


def _excerpt(text: str | None, max_chars: int = 800) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars].rsplit(" ", 1)[0] + "..."
    return text


def build_source_inventory(db: Database, screenshot_ids: list[int]) -> list[SourceInventoryItem]:
    items = []
    for sid in screenshot_ids:
        row = db.query_one("SELECT * FROM screenshots WHERE id = ?", (sid,))
        if row is None:
            continue
        tag_rows = db.query(
            "SELECT t.name FROM screenshot_tags st JOIN tags t ON t.id = st.tag_id WHERE st.screenshot_id = ?",
            (sid,),
        )
        entity_rows = db.query(
            "SELECT e.name, e.entity_type FROM screenshot_entities se JOIN entities e ON e.id = se.entity_id WHERE se.screenshot_id = ?",
            (sid,),
        )
        note_rows = db.query(
            "SELECT body FROM notes WHERE screenshot_id = ? ORDER BY created_at ASC", (sid,)
        )

        uncertainty = []
        if row["processing_status"] != "PROCESSED":
            uncertainty.append(f"processing_status is {row['processing_status']}; OCR/classification may be incomplete")
        if row["ocr_confidence"] is None:
            uncertainty.append("no OCR confidence score available")
        if not row["classification_confidence"] or row["classification_confidence"] < 0.3:
            uncertainty.append("classification confidence is low or unset -- treat content_type/tags as tentative")
        if not (row["raw_ocr_text"] or "").strip():
            uncertainty.append("OCR produced no usable text for this source")

        items.append(SourceInventoryItem(
            screenshot_id=sid,
            sha256=row["sha256"],
            original_path=row["original_path"],
            title=row["title"],
            ocr_excerpt=_excerpt(row["raw_ocr_text"]),
            corrected_ocr_excerpt=_excerpt(row["corrected_ocr_text"]) or None,
            tags=[t["name"] for t in tag_rows],
            entities=[f"{e['name']} ({e['entity_type']})" for e in entity_rows],
            operator_notes=[n["body"] for n in note_rows],
            system_summary=row["summary"],
            ocr_confidence=row["ocr_confidence"],
            classification_confidence=row["classification_confidence"],
            processing_status=row["processing_status"],
            uncertainty=uncertainty,
        ))
    return items


def render_prompt(
    mode: str,
    objective: str,
    inventory: list[SourceInventoryItem],
    operator_instruction: str = "",
) -> str:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown prompt mode: {mode}")

    templates = load_prompt_templates()
    template = templates.get("modes", {}).get(mode, {})
    label = template.get("label", mode)
    instruction = template.get("instruction", "")

    lines: list[str] = []
    lines.append(f"# FORGEWORLD RESEARCH PROMPT -- {label}")
    lines.append(f"generated_at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"prompt_mode: {mode}")
    lines.append("")
    lines.append("## OPERATOR OBJECTIVE")
    lines.append(objective.strip() if objective.strip() else "(no objective provided)")
    lines.append("")
    lines.append("## TASK INSTRUCTION")
    lines.append(instruction)
    if operator_instruction.strip():
        lines.append("")
        lines.append("## ADDITIONAL OPERATOR INSTRUCTION")
        lines.append(operator_instruction.strip())
    lines.append("")
    lines.append("## TRUTH REQUIREMENTS")
    lines.append("- Treat every item under SOURCE-DERIVED CONTENT as the only verified evidence.")
    lines.append("- Treat OPERATOR NOTES as human commentary, not verified fact.")
    lines.append("- Treat SYSTEM INFERENCE (tags, content type, summaries) as machine-generated and unverified.")
    lines.append("- Never state or imply that UNKNOWN INFORMATION is known.")
    lines.append("- Do not claim this prompt or its output was sent to, or reviewed by, any external system.")
    lines.append("")
    lines.append(f"## SOURCE-DERIVED CONTENT ({len(inventory)} source(s))")

    if not inventory:
        lines.append("(no sources selected)")

    for item in inventory:
        lines.append("")
        lines.append(f"### SOURCE {item.screenshot_id}")
        lines.append(f"- sha256: {item.sha256}")
        lines.append(f"- original_path: {item.original_path}")
        lines.append(f"- title: {item.title or 'UNKNOWN'}")
        lines.append(f"- processing_status: {item.processing_status}")
        lines.append(f"- ocr_confidence: {item.ocr_confidence if item.ocr_confidence is not None else 'UNKNOWN'}")
        lines.append(f"- classification_confidence: {item.classification_confidence if item.classification_confidence is not None else 'UNKNOWN'}")
        lines.append("- raw OCR excerpt:")
        lines.append(f"  {item.ocr_excerpt or '(no OCR text)'}")
        if item.corrected_ocr_excerpt:
            lines.append("- operator-corrected OCR excerpt:")
            lines.append(f"  {item.corrected_ocr_excerpt}")

        lines.append("")
        lines.append("#### SYSTEM INFERENCE")
        lines.append(f"- tags: {', '.join(item.tags) if item.tags else 'UNKNOWN'}")
        lines.append(f"- entities: {', '.join(item.entities) if item.entities else 'UNKNOWN'}")
        lines.append(f"- system summary: {item.system_summary or 'UNKNOWN'}")

        lines.append("")
        lines.append("#### OPERATOR NOTES")
        if item.operator_notes:
            for note in item.operator_notes:
                lines.append(f"- {note}")
        else:
            lines.append("- (none recorded)")

        lines.append("")
        lines.append("#### UNKNOWN INFORMATION / UNCERTAINTY")
        if item.uncertainty:
            for u in item.uncertainty:
                lines.append(f"- {u}")
        else:
            lines.append("- none flagged")

    lines.append("")
    lines.append("## REQUESTED OUTPUT")
    lines.append(f"Produce output for prompt mode {mode} using only the SOURCE-DERIVED CONTENT above,")
    lines.append("clearly separating any new synthesis you add as SYSTEM INFERENCE from what the sources state.")

    return "\n".join(lines)


def save_generated_prompt(db: Database, mode: str, objective: str, screenshot_ids: list[int], content: str) -> int:
    import json
    cur = db.execute(
        "INSERT INTO generated_prompts (mode, objective, screenshot_ids, content, created_at) VALUES (?,?,?,?,?)",
        (mode, objective, json.dumps(screenshot_ids), content, utcnow()),
    )
    return cur.lastrowid


def save_prompt_template(db: Database, mode: str, name: str, instruction: str) -> int:
    cur = db.execute(
        "INSERT INTO prompt_templates (mode, name, instruction, is_operator_saved, created_at) VALUES (?,?,?,1,?)",
        (mode, name, instruction, utcnow()),
    )
    return cur.lastrowid
