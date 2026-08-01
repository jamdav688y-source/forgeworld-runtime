"""Screenshot discovery, ingestion, deterministic classification.

Primary laws enforced here:
  - original screenshots are never modified, renamed, moved, or deleted
  - a stable SHA-256 identity gates all deduplication
  - every derivative artifact keeps its source screenshot ID, hash,
    original path, processing status, timestamp, and known uncertainty
  - repeated scans are idempotent
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    Settings,
    SourceLocation,
    SUPPORTED_IMAGE_EXTENSIONS,
    load_classification_rules,
)
from database import Database, utcnow
from ocr import run_ocr, OCR_STATE_PASS, OCR_STATE_EMPTY
from summarizer import build_labeled_summary

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None  # type: ignore


STATUS_PENDING = "PENDING"
STATUS_PROCESSED = "PROCESSED"
STATUS_FAILED = "FAILED"


class PathTraversalError(ValueError):
    pass


@dataclass
class IngestOutcome:
    status: str  # NEW | DUPLICATE | SKIPPED | ERROR
    screenshot_id: int | None = None
    message: str = ""
    path: str = ""


@dataclass
class ScanSummary:
    started_at: str
    finished_at: str = ""
    scanned: int = 0
    new_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    outcomes: list[IngestOutcome] = field(default_factory=list)


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def resolve_within_source(candidate: Path, source_root: Path) -> Path:
    """Resolve candidate to an absolute path and confirm it is inside
    source_root. Raises PathTraversalError otherwise."""
    resolved_root = source_root.expanduser().resolve()
    resolved_candidate = candidate.expanduser().resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalError(
            f"{resolved_candidate} is not inside approved source {resolved_root}"
        )
    return resolved_candidate


def is_supported_image(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def discover_candidates(source: SourceLocation) -> list[Path]:
    root = source.expanded_path()
    if not root.is_dir():
        return []
    candidates = []
    for entry in sorted(root.iterdir()):
        if entry.is_file() and is_supported_image(entry):
            candidates.append(entry)
    return candidates


def create_preview(image_path: Path, sha256: str, max_dimension: int, previews_dir: Path) -> Path | None:
    if Image is None:
        return None
    previews_dir.mkdir(parents=True, exist_ok=True)
    dest = previews_dir / f"{sha256}.jpg"
    if dest.exists():
        return dest
    try:
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        width, height = img.size
        largest = max(width, height)
        if largest > max_dimension:
            scale = max_dimension / float(largest)
            img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
        img.save(dest, "JPEG", quality=85)
        return dest
    except Exception:
        return None


@dataclass
class ClassificationResult:
    content_type: str
    content_type_confidence: float
    domain_tags: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    overall_confidence: float


def classify_text(filename: str, ocr_text: str, rules: dict[str, Any] | None = None) -> ClassificationResult:
    """Deterministic, inspectable rule matching. Every tag/entity records
    the rule that triggered it, a confidence score, and a rationale."""
    if rules is None:
        rules = load_classification_rules()

    haystack = f"{filename}\n{ocr_text or ''}".lower()

    best_content_type = "unknown"
    best_content_confidence = 0.0
    for rule in rules.get("content_type_rules", []):
        matched = [kw for kw in rule.get("keywords", []) if kw.lower() in haystack]
        if matched and rule.get("confidence", 0) > best_content_confidence:
            best_content_type = rule["content_type"]
            best_content_confidence = rule["confidence"]

    domain_tags: list[dict[str, Any]] = []
    for rule in rules.get("domain_rules", []):
        matched = [kw for kw in rule.get("keywords", []) if kw.lower() in haystack]
        if matched:
            domain_tags.append({
                "name": rule["domain"],
                "confidence": rule.get("confidence", 0.5),
                "rationale": f"matched keyword(s): {', '.join(matched[:3])}",
                "rule_id": rule["rule_id"],
            })

    entities: list[dict[str, Any]] = []
    for entity_type, names in rules.get("entity_rules", {}).items():
        for name in names:
            if name.lower() in haystack:
                entities.append({
                    "name": name,
                    "entity_type": entity_type,
                    "confidence": 0.6,
                    "rationale": f"literal match of '{name}' in filename/OCR text",
                    "rule_id": f"entity_{entity_type}",
                })

    if not domain_tags:
        domain_tags.append({
            "name": "unknown",
            "confidence": 0.0,
            "rationale": "no configured domain rule matched",
            "rule_id": "domain_fallback_unknown",
        })

    confidences = [best_content_confidence] + [t["confidence"] for t in domain_tags if t["name"] != "unknown"]
    overall_confidence = max(confidences) if confidences else 0.0

    return ClassificationResult(
        content_type=best_content_type,
        content_type_confidence=best_content_confidence,
        domain_tags=domain_tags,
        entities=entities,
        overall_confidence=round(overall_confidence, 3),
    )


def _get_or_create_tag(db: Database, name: str) -> int:
    row = db.query_one("SELECT id FROM tags WHERE name = ?", (name,))
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO tags (name) VALUES (?)", (name,))
    return cur.lastrowid


def _get_or_create_entity(db: Database, name: str, entity_type: str) -> int:
    row = db.query_one("SELECT id FROM entities WHERE name = ? AND entity_type = ?", (name, entity_type))
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO entities (name, entity_type) VALUES (?, ?)", (name, entity_type))
    return cur.lastrowid


def _get_or_create_source_location(db: Database, source: SourceLocation) -> int:
    row = db.query_one("SELECT id FROM source_locations WHERE path = ?", (source.path,))
    if row:
        db.execute(
            "UPDATE source_locations SET label = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (source.label, int(source.enabled), utcnow(), row["id"]),
        )
        return row["id"]
    cur = db.execute(
        "INSERT INTO source_locations (path, label, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (source.path, source.label, int(source.enabled), utcnow(), utcnow()),
    )
    return cur.lastrowid


def ingest_file(
    db: Database,
    settings: Settings,
    source: SourceLocation,
    file_path: Path,
    project_root: Path,
    rules: dict[str, Any] | None = None,
) -> IngestOutcome:
    source_location_id = _get_or_create_source_location(db, source)

    try:
        resolved = resolve_within_source(file_path, source.expanded_path())
    except PathTraversalError as exc:
        db.record_event(None, "REJECTED_PATH_TRAVERSAL", str(exc))
        return IngestOutcome(status="ERROR", message=str(exc), path=str(file_path))

    if not resolved.is_file() or not is_supported_image(resolved):
        return IngestOutcome(status="SKIPPED", message="unsupported or missing file", path=str(resolved))

    try:
        digest = sha256_of_file(resolved)
    except OSError as exc:
        db.record_event(None, "HASH_FAILED", f"{resolved}: {exc}")
        return IngestOutcome(status="ERROR", message=str(exc), path=str(resolved))

    existing = db.query_one("SELECT id FROM screenshots WHERE sha256 = ?", (digest,))
    if existing is not None:
        screenshot_id = existing["id"]
        already_linked = db.query_one(
            "SELECT 1 FROM screenshot_sources WHERE screenshot_id = ? AND source_location_id = ?",
            (screenshot_id, source_location_id),
        )
        if not already_linked:
            db.execute(
                "INSERT INTO screenshot_sources (screenshot_id, source_location_id, discovered_at) VALUES (?, ?, ?)",
                (screenshot_id, source_location_id, utcnow()),
            )
        db.record_event(screenshot_id, "DUPLICATE_SKIPPED", f"hash already present at {resolved}")
        return IngestOutcome(status="DUPLICATE", screenshot_id=screenshot_id, path=str(resolved))

    stat = resolved.stat()
    width = height = None
    image_format = resolved.suffix.lstrip(".").lower()
    if Image is not None:
        try:
            with Image.open(resolved) as im:
                width, height = im.size
                image_format = (im.format or image_format).lower()
        except Exception:
            pass

    now = utcnow()
    cur = db.execute(
        """INSERT INTO screenshots (
            sha256, original_path, filename, file_size, width, height, image_format,
            captured_at, discovered_at, processing_status, source_platform, content_type,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            digest, str(resolved), resolved.name, stat.st_size, width, height, image_format,
            None, now, STATUS_PENDING, None, "unknown", now, now,
        ),
    )
    screenshot_id = cur.lastrowid
    db.execute(
        "INSERT INTO screenshot_sources (screenshot_id, source_location_id, discovered_at) VALUES (?, ?, ?)",
        (screenshot_id, source_location_id, now),
    )
    db.record_event(screenshot_id, "DISCOVERED", f"new screenshot at {resolved}")

    previews_dir = project_root / "runtime" / "previews"
    create_preview(resolved, digest, settings.max_preview_dimension, previews_dir)

    try:
        ocr_result = run_ocr(
            resolved,
            language=settings.ocr_language,
            timeout_seconds=settings.ocr_timeout_seconds,
            max_dimension=settings.max_ocr_dimension,
        )
    except Exception as exc:
        db.execute(
            "UPDATE screenshots SET processing_status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (STATUS_FAILED, f"OCR crashed: {exc}", utcnow(), screenshot_id),
        )
        db.record_event(screenshot_id, "OCR_CRASHED", str(exc))
        return IngestOutcome(status="NEW", screenshot_id=screenshot_id, message="ocr crashed", path=str(resolved))

    db.execute(
        """INSERT INTO ocr_extractions (
            screenshot_id, raw_text, normalized_text, engine_name, engine_version, language,
            extracted_at, success_state, warnings, errors, confidence, duration_ms
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            screenshot_id, ocr_result.raw_text, ocr_result.normalized_text, ocr_result.engine_name,
            ocr_result.engine_version, ocr_result.language, ocr_result.extracted_at, ocr_result.success_state,
            "; ".join(ocr_result.warnings), "; ".join(ocr_result.errors), ocr_result.confidence,
            ocr_result.duration_ms,
        ),
    )

    classification = classify_text(resolved.name, ocr_result.normalized_text, rules)
    for tag in classification.domain_tags:
        tag_id = _get_or_create_tag(db, tag["name"])
        db.execute(
            """INSERT INTO screenshot_tags (screenshot_id, tag_id, confidence, rationale, rule_id, operator_assigned)
               VALUES (?,?,?,?,?,0)
               ON CONFLICT(screenshot_id, tag_id) DO UPDATE SET
                 confidence=excluded.confidence, rationale=excluded.rationale, rule_id=excluded.rule_id""",
            (screenshot_id, tag_id, tag["confidence"], tag["rationale"], tag["rule_id"]),
        )
    for ent in classification.entities:
        entity_id = _get_or_create_entity(db, ent["name"], ent["entity_type"])
        db.execute(
            """INSERT INTO screenshot_entities (screenshot_id, entity_id, confidence, rationale, rule_id)
               VALUES (?,?,?,?,?)
               ON CONFLICT(screenshot_id, entity_id) DO UPDATE SET
                 confidence=excluded.confidence, rationale=excluded.rationale, rule_id=excluded.rule_id""",
            (screenshot_id, entity_id, ent["confidence"], ent["rationale"], ent["rule_id"]),
        )

    summary = ""
    if ocr_result.success_state in (OCR_STATE_PASS, OCR_STATE_EMPTY):
        summary = build_labeled_summary(ocr_result.normalized_text)

    title = resolved.stem.replace("_", " ").replace("-", " ").strip() or None

    db.execute(
        """UPDATE screenshots SET
            processing_status = ?, processed_at = ?, content_type = ?, title = ?, summary = ?,
            raw_ocr_text = ?, ocr_confidence = ?, classification_confidence = ?, updated_at = ?
           WHERE id = ?""",
        (
            STATUS_PROCESSED, utcnow(), classification.content_type, title, summary,
            ocr_result.normalized_text, ocr_result.confidence, classification.overall_confidence,
            utcnow(), screenshot_id,
        ),
    )
    db.record_event(screenshot_id, "PROCESSED", f"ocr={ocr_result.success_state} content_type={classification.content_type}")

    return IngestOutcome(status="NEW", screenshot_id=screenshot_id, path=str(resolved))


def scan(
    db: Database,
    settings: Settings,
    sources: list[SourceLocation],
    project_root: Path,
    batch_limit: int | None = None,
) -> ScanSummary:
    """Idempotent bounded scan across all enabled + existing sources."""
    rules = load_classification_rules()
    started_at = utcnow()
    summary = ScanSummary(started_at=started_at)
    limit = batch_limit if batch_limit is not None else settings.max_normal_batch

    processed_count = 0
    for source in sources:
        if not source.enabled or not source.exists():
            continue
        for candidate in discover_candidates(source):
            if processed_count >= limit:
                break
            outcome = ingest_file(db, settings, source, candidate, project_root, rules)
            summary.outcomes.append(outcome)
            summary.scanned += 1
            if outcome.status == "NEW":
                summary.new_count += 1
                processed_count += 1
            elif outcome.status == "DUPLICATE":
                summary.duplicate_count += 1
            elif outcome.status == "SKIPPED":
                summary.skipped_count += 1
            else:
                summary.error_count += 1
        if processed_count >= limit:
            break

    summary.finished_at = utcnow()
    db.record_event(
        None,
        "SCAN_COMPLETE",
        f"scanned={summary.scanned} new={summary.new_count} dup={summary.duplicate_count} "
        f"skipped={summary.skipped_count} errors={summary.error_count}",
    )
    return summary
