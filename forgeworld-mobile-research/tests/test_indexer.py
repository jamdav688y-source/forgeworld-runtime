from pathlib import Path

import pytest

from config import SourceLocation
from database import utcnow
from indexer import (
    classify_text,
    ingest_file,
    resolve_within_source,
    sha256_of_file,
    scan,
    PathTraversalError,
    STATUS_FAILED,
    STATUS_PENDING,
)


def _make_image(path: Path, text: str = "") -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 100), "white")
    if text:
        d = ImageDraw.Draw(img)
        d.text((5, 40), text, fill="black")
    img.save(path)


def test_sha256_of_file_is_stable(tmp_path):
    f = tmp_path / "a.png"
    _make_image(f)
    h1 = sha256_of_file(f)
    h2 = sha256_of_file(f)
    assert h1 == h2
    assert len(h1) == 64


def test_resolve_within_source_rejects_traversal(tmp_path):
    source_root = tmp_path / "Screenshots"
    source_root.mkdir()
    outside = tmp_path / "outside" / "evil.png"
    outside.parent.mkdir()
    outside.write_bytes(b"x")

    with pytest.raises(PathTraversalError):
        resolve_within_source(outside, source_root)


def test_classify_text_deterministic_and_inspectable():
    result = classify_text("shot.png", "This screenshot discusses agent systems and governance policy")
    names = [t["name"] for t in result.domain_tags]
    assert "agent_systems" in names
    assert "governance" in names
    for tag in result.domain_tags:
        assert "rule_id" in tag and "rationale" in tag and "confidence" in tag


def test_ingest_is_idempotent(db, settings, project_root, tmp_path):
    source_dir = tmp_path / "Screenshots"
    source_dir.mkdir()
    _make_image(source_dir / "one.png", "Agent governance terminal")
    source = SourceLocation(path=str(source_dir), label="fixture", enabled=True)

    summary1 = scan(db, settings, [source], project_root, batch_limit=10)
    assert summary1.new_count == 1
    assert summary1.duplicate_count == 0

    summary2 = scan(db, settings, [source], project_root, batch_limit=10)
    assert summary2.new_count == 0
    assert summary2.duplicate_count == 1

    total = db.query_one("SELECT COUNT(*) c FROM screenshots")["c"]
    assert total == 1


def test_ingest_preserves_original_file_unchanged(db, settings, project_root, tmp_path):
    source_dir = tmp_path / "Screenshots"
    source_dir.mkdir()
    image_path = source_dir / "one.png"
    _make_image(image_path, "Some text")
    before = image_path.read_bytes()
    source = SourceLocation(path=str(source_dir), label="fixture", enabled=True)

    scan(db, settings, [source], project_root, batch_limit=10)

    after = image_path.read_bytes()
    assert before == after


def test_interrupted_scan_resumes_stranded_pending_row(db, settings, project_root, tmp_path):
    """Simulates a process kill right after the screenshots row INSERT but
    before OCR/classification ran (see indexer.ingest_file). A screenshot
    stuck at PENDING with no OCR text must be completed on the next scan,
    not permanently treated as a duplicate."""
    source_dir = tmp_path / "Screenshots"
    source_dir.mkdir()
    image_path = source_dir / "stranded.png"
    _make_image(image_path, "Interrupted scan governance agent")
    source = SourceLocation(path=str(source_dir), label="fixture", enabled=True)

    digest = sha256_of_file(image_path)
    now = utcnow()
    db.execute(
        """INSERT INTO screenshots (sha256, original_path, filename, discovered_at,
           processing_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)""",
        (digest, str(image_path.resolve()), image_path.name, now, STATUS_PENDING, now, now),
    )

    summary = scan(db, settings, [source], project_root, batch_limit=10)

    assert summary.new_count == 0
    assert summary.resumed_count == 1
    assert summary.duplicate_count == 0

    row = db.query_one("SELECT processing_status, raw_ocr_text FROM screenshots WHERE sha256 = ?", (digest,))
    assert row["processing_status"] == "PROCESSED"
    assert row["raw_ocr_text"]


def test_interrupted_scan_resumes_failed_row(db, settings, project_root, tmp_path):
    """A row that previously failed OCR (e.g. Tesseract crashed) should
    also be retried on the next scan rather than staying FAILED forever."""
    source_dir = tmp_path / "Screenshots"
    source_dir.mkdir()
    image_path = source_dir / "failed.png"
    _make_image(image_path, "Retry me")
    source = SourceLocation(path=str(source_dir), label="fixture", enabled=True)

    digest = sha256_of_file(image_path)
    now = utcnow()
    db.execute(
        """INSERT INTO screenshots (sha256, original_path, filename, discovered_at,
           processing_status, error_message, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        (digest, str(image_path.resolve()), image_path.name, now, STATUS_FAILED, "OCR crashed: boom", now, now),
    )

    summary = scan(db, settings, [source], project_root, batch_limit=10)

    assert summary.resumed_count == 1
    row = db.query_one("SELECT processing_status, error_message FROM screenshots WHERE sha256 = ?", (digest,))
    assert row["processing_status"] == "PROCESSED"
    assert row["error_message"] is None


def test_already_processed_row_stays_duplicate(db, settings, project_root, tmp_path):
    """A fully processed row must not be reprocessed on rescan -- only
    PENDING/FAILED rows get resumed."""
    source_dir = tmp_path / "Screenshots"
    source_dir.mkdir()
    image_path = source_dir / "done.png"
    _make_image(image_path, "Already done")
    source = SourceLocation(path=str(source_dir), label="fixture", enabled=True)

    scan(db, settings, [source], project_root, batch_limit=10)
    summary2 = scan(db, settings, [source], project_root, batch_limit=10)

    assert summary2.resumed_count == 0
    assert summary2.duplicate_count == 1
