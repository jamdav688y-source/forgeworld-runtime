from search import SearchFilters, search_screenshots, _build_fts_query


def _insert_screenshot(db, sha, filename, raw_ocr_text, tags=()):
    cur = db.execute(
        """INSERT INTO screenshots (sha256, original_path, filename, discovered_at,
           processing_status, created_at, updated_at, title, raw_ocr_text, classification_confidence)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (sha, f"/x/{filename}", filename, "2026-01-01T00:00:00Z", "PROCESSED",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", filename, raw_ocr_text, 0.6),
    )
    sid = cur.lastrowid
    for tag in tags:
        row = db.query_one("SELECT id FROM tags WHERE name = ?", (tag,))
        tag_id = row["id"] if row else db.execute("INSERT INTO tags (name) VALUES (?)", (tag,)).lastrowid
        db.execute(
            "INSERT INTO screenshot_tags (screenshot_id, tag_id, confidence, rationale, rule_id) VALUES (?,?,?,?,?)",
            (sid, tag_id, 0.6, "test", "rule_test"),
        )
    return sid


def test_fts_query_sanitizes_operators(db):
    # Operator-typed FTS syntax (OR, unterminated quotes) must never raise --
    # every token becomes a safely double-quoted literal.
    q = _build_fts_query('governance OR "unterminated')
    assert q.count('"') % 2 == 0
    db.query("SELECT rowid FROM screenshots_fts WHERE screenshots_fts MATCH ?", (q,))


def test_keyword_search_finds_match(db):
    _insert_screenshot(db, "h1", "a.png", "agent systems governance discussion")
    _insert_screenshot(db, "h2", "b.png", "unrelated content about cinema")
    results = search_screenshots(db, SearchFilters(keywords="governance"))
    assert len(results) == 1
    assert results[0]["filename"] == "a.png"


def test_tag_filter(db):
    _insert_screenshot(db, "h1", "a.png", "text", tags=["linkedin"])
    _insert_screenshot(db, "h2", "b.png", "text", tags=["security"])
    results = search_screenshots(db, SearchFilters(tags=["linkedin"]))
    assert len(results) == 1
    assert results[0]["filename"] == "a.png"


def test_min_confidence_filter(db):
    _insert_screenshot(db, "h1", "a.png", "text")
    results = search_screenshots(db, SearchFilters(min_confidence=0.9))
    assert results == []
