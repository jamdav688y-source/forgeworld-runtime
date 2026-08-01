from pathlib import Path

import pytest

from config import SourceLocation
from indexer import (
    classify_text,
    ingest_file,
    resolve_within_source,
    sha256_of_file,
    scan,
    PathTraversalError,
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
