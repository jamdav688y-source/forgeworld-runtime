"""SQLite persistence layer for the ForgeWorld Mobile Research Companion.

One SQLite database. No ORM, no Pydantic: parameterized SQL + dataclasses.
FTS5 is kept in sync with triggers so callers never touch the FTS table
directly.
"""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config import Settings

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    image_format TEXT,
    captured_at TEXT,
    discovered_at TEXT NOT NULL,
    processed_at TEXT,
    processing_status TEXT NOT NULL DEFAULT 'PENDING',
    source_platform TEXT,
    content_type TEXT DEFAULT 'unknown',
    title TEXT,
    summary TEXT,
    raw_ocr_text TEXT,
    corrected_ocr_text TEXT,
    ocr_confidence REAL,
    classification_confidence REAL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screenshot_sources (
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    source_location_id INTEGER NOT NULL REFERENCES source_locations(id) ON DELETE CASCADE,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (screenshot_id, source_location_id)
);

CREATE TABLE IF NOT EXISTS ocr_extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    raw_text TEXT,
    normalized_text TEXT,
    engine_name TEXT NOT NULL DEFAULT 'tesseract',
    engine_version TEXT,
    language TEXT NOT NULL DEFAULT 'eng',
    extracted_at TEXT NOT NULL,
    success_state TEXT NOT NULL,
    warnings TEXT,
    errors TEXT,
    confidence REAL,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS ocr_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    previous_text TEXT,
    corrected_text TEXT NOT NULL,
    revision_note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    UNIQUE(name, entity_type)
);

CREATE TABLE IF NOT EXISTS screenshot_entities (
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence REAL NOT NULL DEFAULT 0,
    rationale TEXT,
    rule_id TEXT,
    PRIMARY KEY (screenshot_id, entity_id)
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS screenshot_tags (
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence REAL NOT NULL DEFAULT 0,
    rationale TEXT,
    rule_id TEXT,
    operator_assigned INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (screenshot_id, tag_id)
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, screenshot_id)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER NOT NULL REFERENCES screenshots(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    author TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    is_operator_saved INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    objective TEXT,
    screenshot_ids TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screenshot_id INTEGER REFERENCES screenshots(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_screenshots_status ON screenshots(processing_status);
CREATE INDEX IF NOT EXISTS idx_screenshots_content_type ON screenshots(content_type);
CREATE INDEX IF NOT EXISTS idx_screenshot_tags_tag ON screenshot_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_screenshot_entities_entity ON screenshot_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_processing_events_screenshot ON processing_events(screenshot_id);
CREATE INDEX IF NOT EXISTS idx_notes_screenshot ON notes(screenshot_id);

CREATE VIRTUAL TABLE IF NOT EXISTS screenshots_fts USING fts5(
    title,
    summary,
    raw_ocr_text,
    corrected_ocr_text,
    tags_text,
    entities_text,
    notes_text,
    author_text
);

CREATE TRIGGER IF NOT EXISTS trg_screenshots_ai AFTER INSERT ON screenshots BEGIN
    INSERT INTO screenshots_fts (rowid, title, summary, raw_ocr_text, corrected_ocr_text, tags_text, entities_text, notes_text, author_text)
    VALUES (NEW.id, NEW.title, NEW.summary, NEW.raw_ocr_text, NEW.corrected_ocr_text, '', '', '', '');
END;

CREATE TRIGGER IF NOT EXISTS trg_screenshots_au AFTER UPDATE ON screenshots BEGIN
    UPDATE screenshots_fts
    SET title = NEW.title,
        summary = NEW.summary,
        raw_ocr_text = NEW.raw_ocr_text,
        corrected_ocr_text = NEW.corrected_ocr_text
    WHERE rowid = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_screenshots_ad AFTER DELETE ON screenshots BEGIN
    DELETE FROM screenshots_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_screenshot_tags_ai AFTER INSERT ON screenshot_tags BEGIN
    UPDATE screenshots_fts
    SET tags_text = (
        SELECT COALESCE(group_concat(t.name, ' '), '')
        FROM tags t JOIN screenshot_tags st ON t.id = st.tag_id
        WHERE st.screenshot_id = NEW.screenshot_id
    )
    WHERE rowid = NEW.screenshot_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_screenshot_tags_ad AFTER DELETE ON screenshot_tags BEGIN
    UPDATE screenshots_fts
    SET tags_text = (
        SELECT COALESCE(group_concat(t.name, ' '), '')
        FROM tags t JOIN screenshot_tags st ON t.id = st.tag_id
        WHERE st.screenshot_id = OLD.screenshot_id
    )
    WHERE rowid = OLD.screenshot_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_screenshot_entities_ai AFTER INSERT ON screenshot_entities BEGIN
    UPDATE screenshots_fts
    SET entities_text = (
        SELECT COALESCE(group_concat(e.name, ' '), '')
        FROM entities e JOIN screenshot_entities se ON e.id = se.entity_id
        WHERE se.screenshot_id = NEW.screenshot_id
    )
    WHERE rowid = NEW.screenshot_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_screenshot_entities_ad AFTER DELETE ON screenshot_entities BEGIN
    UPDATE screenshots_fts
    SET entities_text = (
        SELECT COALESCE(group_concat(e.name, ' '), '')
        FROM entities e JOIN screenshot_entities se ON e.id = se.entity_id
        WHERE se.screenshot_id = OLD.screenshot_id
    )
    WHERE rowid = OLD.screenshot_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_notes_ai AFTER INSERT ON notes BEGIN
    UPDATE screenshots_fts
    SET notes_text = (
        SELECT COALESCE(group_concat(body, ' '), '') FROM notes WHERE screenshot_id = NEW.screenshot_id
    ),
    author_text = (
        SELECT COALESCE(group_concat(DISTINCT author), '') FROM notes WHERE screenshot_id = NEW.screenshot_id AND author IS NOT NULL
    )
    WHERE rowid = NEW.screenshot_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_notes_au AFTER UPDATE ON notes BEGIN
    UPDATE screenshots_fts
    SET notes_text = (
        SELECT COALESCE(group_concat(body, ' '), '') FROM notes WHERE screenshot_id = NEW.screenshot_id
    ),
    author_text = (
        SELECT COALESCE(group_concat(DISTINCT author), '') FROM notes WHERE screenshot_id = NEW.screenshot_id AND author IS NOT NULL
    )
    WHERE rowid = NEW.screenshot_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_notes_ad AFTER DELETE ON notes BEGIN
    UPDATE screenshots_fts
    SET notes_text = (
        SELECT COALESCE(group_concat(body, ' '), '') FROM notes WHERE screenshot_id = OLD.screenshot_id
    ),
    author_text = (
        SELECT COALESCE(group_concat(DISTINCT author), '') FROM notes WHERE screenshot_id = OLD.screenshot_id AND author IS NOT NULL
    )
    WHERE rowid = OLD.screenshot_id;
END;
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup_existing_database(db_path: Path, backups_dir: Path) -> Path | None:
    """Copy an existing database file to runtime/backups/ with a timestamped name."""
    if not db_path.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backups_dir / f"{db_path.stem}.{stamp}.bak{db_path.suffix}"
    shutil.copy2(db_path, dest)
    return dest


class Database:
    """Thin wrapper around a single sqlite3 connection with WAL + FTS5 schema applied."""

    def __init__(self, settings: Settings, project_root: Path):
        self.settings = settings
        self.project_root = project_root
        self.db_path = settings.database_full_path()
        self.backups_dir = project_root / "runtime" / "backups"
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.settings.sqlite_wal:
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {int(self.settings.sqlite_busy_timeout_ms)}")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connect()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        conn = self.connect()
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def record_event(self, screenshot_id: int | None, event_type: str, message: str = "") -> None:
        self.execute(
            "INSERT INTO processing_events (screenshot_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
            (screenshot_id, event_type, message, utcnow()),
        )

    def database_size_bytes(self) -> int:
        return self.db_path.stat().st_size if self.db_path.exists() else 0


def open_database(settings: Settings, project_root: Path, backup_if_exists: bool = False) -> Database:
    """Open (creating if needed) the canonical database.

    backup_if_exists should only be set True ahead of an intentional schema
    migration or replacement -- not on ordinary app startup, since that
    would write a fresh backup file every launch.
    """
    db = Database(settings, project_root)
    if backup_if_exists and db.db_path.exists():
        backup_existing_database(db.db_path, db.backups_dir)
    db.connect()
    return db
