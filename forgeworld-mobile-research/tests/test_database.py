def test_schema_creates_and_fts_stays_in_sync(db):
    cur = db.execute(
        """INSERT INTO screenshots (sha256, original_path, filename, discovered_at,
           processing_status, created_at, updated_at, title, raw_ocr_text)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ("hash1", "/a/b.png", "b.png", "2026-01-01T00:00:00Z", "PENDING",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "Title", "agent systems text"),
    )
    sid = cur.lastrowid

    rows = db.query("SELECT rowid FROM screenshots_fts WHERE screenshots_fts MATCH ?", ("agent",))
    assert len(rows) == 1

    db.execute("UPDATE screenshots SET title = ? WHERE id = ?", ("New Title", sid))
    row = db.query_one("SELECT title FROM screenshots_fts WHERE rowid = ?", (sid,))
    assert row["title"] == "New Title"

    db.execute("DELETE FROM screenshots WHERE id = ?", (sid,))
    assert db.query_one("SELECT * FROM screenshots_fts WHERE rowid = ?", (sid,)) is None


def test_sha256_is_unique(db):
    db.execute(
        """INSERT INTO screenshots (sha256, original_path, filename, discovered_at,
           processing_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)""",
        ("dup", "/a/1.png", "1.png", "2026-01-01T00:00:00Z", "PENDING",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO screenshots (sha256, original_path, filename, discovered_at,
               processing_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)""",
            ("dup", "/a/2.png", "2.png", "2026-01-01T00:00:00Z", "PENDING",
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
