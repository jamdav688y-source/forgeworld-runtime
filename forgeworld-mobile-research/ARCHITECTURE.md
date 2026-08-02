# Architecture

## Process model

One Python process (`app.py`, Flask, dev server), one SQLite database
(`runtime/database/forgeworld_research.db`), one browser shell
(`templates/index.html` + `static/app.js`) that talks to the process over
a JSON API on `127.0.0.1:5055`. There is no second dashboard, no vector
database server, and no background daemon that outlives the process.

## Modules

| File | Responsibility |
|---|---|
| `config.py` | Loads/saves `config/*.json`; source-directory probing; runtime dir setup. Plain dataclasses, no Pydantic. |
| `database.py` | SQLite schema (DDL), WAL/busy-timeout pragmas, FTS5 virtual table + sync triggers, thin connection wrapper. |
| `ocr.py` | Tesseract invocation via pytesseract on an in-memory derivative image; state machine (`PASS`/`EMPTY`/`FAILED`/`TIMEOUT`). |
| `indexer.py` | Discovery, path-traversal-safe resolution, SHA-256 hashing, dedupe, preview generation, deterministic classification, idempotent scan orchestration. |
| `summarizer.py` | Deterministic extractive summarization, always labeled `SYSTEM_EXTRACTIVE_SUMMARY`. |
| `search.py` | FTS5 query construction (safe against operator-syntax injection) + structured filters. |
| `prompts.py` | Builds the source inventory and renders mode-specific, source-grounded prompt text with explicit SOURCE-DERIVED / OPERATOR NOTES / SYSTEM INFERENCE / UNKNOWN sections. |
| `embeddings.py` | Disabled `SemanticIndexAdapter` -- no heavy imports, no-op by default. |
| `watcher.py` | Bounded polling loop (explicitly enabled only, wired into `app.py`'s settings/`/api/polling/*`); routes through `indexer.scan`. |
| `integrations.py` | Disabled ForgeWorld ecosystem extension points (Cinema Engine, Repository Intelligence, Executive Bootstrap, Knowledge Graph) -- same no-op-adapter pattern as `embeddings.py`. |
| `app.py` | Flask routes: page shell + full JSON API for every tab. |

## Data flow (ingestion)

```
source_paths.json (enabled dirs)
        |
        v
indexer.discover_candidates()  -- list supported image files
        |
        v
indexer.resolve_within_source() -- reject path traversal
        |
        v
indexer.sha256_of_file()        -- streamed hash
        |
        v
   hash exists? --yes--> link source, record DUPLICATE event, stop
        | no
        v
INSERT screenshots (PENDING) + screenshot_sources
        |
        v
indexer.create_preview()        -- bounded JPEG under runtime/previews/
        |
        v
ocr.run_ocr()                   -- derivative-only OCR, never touches original
        |
        v
INSERT ocr_extractions           (full lineage, even on FAILED/TIMEOUT)
        |
        v
indexer.classify_text()          -- rule-based tags/entities with rationale
        |
        v
summarizer.build_labeled_summary()
        |
        v
UPDATE screenshots (PROCESSED, title, summary, content_type, ...)
        |
        v
FTS5 triggers keep screenshots_fts in sync automatically
```

Every step that touches the database also calls
`Database.record_event()`, so `processing_events` is a full audit trail
per screenshot (and for scan-level events, with `screenshot_id = NULL`).

## FTS5 sync strategy

`screenshots_fts` is a plain (non-contentless) FTS5 table so it supports
`UPDATE`/`DELETE` directly. Triggers on `screenshots`, `screenshot_tags`,
`screenshot_entities`, and `notes` keep it synchronized:

- `screenshots` INSERT/UPDATE/DELETE keep `title`/`summary`/`raw_ocr_text`/
  `corrected_ocr_text` current.
- `screenshot_tags` / `screenshot_entities` INSERT/DELETE recompute the
  aggregated `tags_text` / `entities_text` columns via a `group_concat`
  subquery scoped to that screenshot.
- `notes` INSERT/UPDATE/DELETE recompute `notes_text` and `author_text`
  the same way.

This means callers never write to `screenshots_fts` directly -- they only
write to the normalized tables, and the FTS index follows automatically.
Verified by `tests/test_database.py`.

## Search query safety

Operator search input goes through `search._build_fts_query()`, which
tokenizes on quoted phrases vs. bare words and wraps every token in
literal double quotes (escaping any embedded quote as `""`). This means
FTS5 query operators typed by the user (`OR`, `NOT`, `-foo`, `*`) are
always treated as literal text, never as query syntax, so malformed or
adversarial input can't break search. All values still flow through
parameterized SQL (`?` placeholders) regardless -- there is no string
interpolation into SQL anywhere in the codebase.

## Semantic search boundary

`embeddings.py` defines `SemanticIndexAdapter` (a `Protocol`) and a
`DisabledSemanticIndexAdapter` that is always returned by
`get_semantic_index_adapter()`. No embedding library is imported. This
stays disabled until FTS5 has been used in real operation and its
shortcomings are documented (see `KNOWN_LIMITATIONS.md`).

## ForgeWorld integration boundary

`integrations.py` reserves four extension points for later, explicitly
authorized cycles: Cinema Engine, Repository Intelligence, Executive
Bootstrap, and Knowledge Graph. Each is a disabled adapter (same
`Protocol` + no-op-default pattern as `embeddings.py`) whose methods raise
`NotImplementedError` if ever called. `/api/system_status` reports each
adapter's `describe()` output so the operator can see what's reserved
without any of it doing anything. Nothing else in the codebase imports or
calls these adapters -- the app is fully functional with all four absent.

## Resource governance

`config/settings.json` bounds every expensive operation: one OCR job at a
time, batch caps (`max_initial_batch` / `max_normal_batch`), preview/OCR
dimension caps, and manual scanning as the default (bounded polling and
scheduled scanning are both off by default in `watcher.py`).
