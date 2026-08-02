"""SQLite FTS5 search layer.

This is keyword/phrase full-text search -- not semantic search. Relevance
ranking reflects term matching only and implies nothing about correctness
or authority of the underlying content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from database import Database

_TOKEN_RE = re.compile(r'"([^"]+)"|(\S+)')


def _build_fts_query(raw: str) -> str:
    """Turn free-text operator input into a safe, implicit-AND FTS5 query.

    Quoted phrases are preserved as phrases; every other token is treated
    as a literal term (double-quoted) so FTS5 query-syntax operators typed
    by the operator (AND/OR/NOT/-/*) can't break the query.
    """
    if not raw or not raw.strip():
        return ""
    terms = []
    for match in _TOKEN_RE.finditer(raw.strip()):
        phrase, word = match.group(1), match.group(2)
        token = phrase if phrase is not None else word
        token = token.replace('"', '""').strip()
        if token:
            terms.append(f'"{token}"')
    return " ".join(terms)


@dataclass
class SearchFilters:
    keywords: str = ""
    tags: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    collection_id: int | None = None
    min_confidence: float | None = None
    sort: str = "relevance"  # relevance | newest | oldest
    limit: int = 25
    offset: int = 0


def search_screenshots(db: Database, filters: SearchFilters) -> list[dict]:
    fts_query = _build_fts_query(filters.keywords)

    joins = []
    where = []
    params: list = []

    base_select = """
        SELECT s.id, s.filename, s.original_path, s.title, s.summary, s.source_platform,
               s.content_type, s.discovered_at, s.captured_at, s.processing_status,
               s.ocr_confidence, s.classification_confidence, s.sha256
    """

    if fts_query:
        joins.append("JOIN screenshots_fts fts ON fts.rowid = s.id")
        where.append("screenshots_fts MATCH ?")
        params.append(fts_query)
        base_select += ", snippet(screenshots_fts, -1, '[', ']', '...', 12) AS excerpt, bm25(screenshots_fts) AS rank"
    else:
        base_select += ", NULL AS excerpt, 0 AS rank"

    if filters.tags:
        placeholders = ",".join("?" for _ in filters.tags)
        where.append(f"""s.id IN (
            SELECT st.screenshot_id FROM screenshot_tags st JOIN tags t ON t.id = st.tag_id
            WHERE t.name IN ({placeholders})
        )""")
        params.extend(filters.tags)

    if filters.platforms:
        placeholders = ",".join("?" for _ in filters.platforms)
        where.append(f"s.source_platform IN ({placeholders})")
        params.extend(filters.platforms)

    if filters.content_types:
        placeholders = ",".join("?" for _ in filters.content_types)
        where.append(f"s.content_type IN ({placeholders})")
        params.extend(filters.content_types)

    if filters.date_from:
        where.append("s.discovered_at >= ?")
        params.append(filters.date_from)

    if filters.date_to:
        where.append("s.discovered_at <= ?")
        params.append(filters.date_to)

    if filters.collection_id is not None:
        where.append("s.id IN (SELECT screenshot_id FROM collection_items WHERE collection_id = ?)")
        params.append(filters.collection_id)

    if filters.min_confidence is not None:
        where.append("COALESCE(s.classification_confidence, 0) >= ?")
        params.append(filters.min_confidence)

    sql = base_select + " FROM screenshots s " + " ".join(joins)
    if where:
        sql += " WHERE " + " AND ".join(where)

    if filters.sort == "newest":
        sql += " ORDER BY s.discovered_at DESC"
    elif filters.sort == "oldest":
        sql += " ORDER BY s.discovered_at ASC"
    else:
        sql += " ORDER BY rank ASC" if fts_query else " ORDER BY s.discovered_at DESC"

    sql += " LIMIT ? OFFSET ?"
    params.extend([filters.limit, filters.offset])

    rows = db.query(sql, tuple(params))
    results = []
    for row in rows:
        row_dict = dict(row)
        tag_rows = db.query(
            """SELECT t.name, st.confidence FROM screenshot_tags st JOIN tags t ON t.id = st.tag_id
               WHERE st.screenshot_id = ? ORDER BY st.confidence DESC LIMIT 5""",
            (row_dict["id"],),
        )
        row_dict["top_tags"] = [dict(t) for t in tag_rows]
        row_dict["preview_path"] = f"/previews/{row_dict['sha256']}.jpg"
        results.append(row_dict)
    return results
