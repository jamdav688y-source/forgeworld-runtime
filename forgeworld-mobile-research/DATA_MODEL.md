# Data Model

Single SQLite database at `runtime/database/forgeworld_research.db`.
`PRAGMA foreign_keys = ON`, `journal_mode = WAL`, `busy_timeout = 5000`.
No image binaries are stored in SQLite -- only paths and bounded cached
previews on disk (`runtime/previews/<sha256>.jpg`).

## Tables

### screenshots
The canonical record for one discovered image, keyed by a unique
`sha256`. Columns: `id`, `sha256` (UNIQUE), `original_path`, `filename`,
`file_size`, `width`, `height`, `image_format`, `captured_at`,
`discovered_at`, `processed_at`, `processing_status`
(`PENDING`/`PROCESSED`/`FAILED`), `source_platform`, `content_type`,
`title`, `summary`, `raw_ocr_text`, `corrected_ocr_text`,
`ocr_confidence`, `classification_confidence`, `error_message`,
`created_at`, `updated_at`.

### source_locations
Approved directories that have ever been scanned or configured, mirrors
(and is kept in sync with) `config/source_paths.json`.

### screenshot_sources
Many-to-many: a screenshot can be discovered under more than one enabled
source location without creating duplicate screenshot rows.

### ocr_extractions
One row per OCR attempt (initial run, manual rerun). Preserves
`raw_text`, `normalized_text`, `engine_name`, `engine_version`,
`language`, `extracted_at`, `success_state`
(`PASS`/`EMPTY`/`FAILED`/`TIMEOUT`/`UNUSABLE`/`CORRECTED`), `warnings`,
`errors`, `confidence`, `duration_ms`. Nothing here is ever deleted or
overwritten -- reruns append new rows.

### ocr_revisions
Operator corrections. Each revision stores `previous_text` and
`corrected_text` so a correction never destroys what came before it;
`screenshots.raw_ocr_text` (from the original extraction) is separately
never touched by a correction.

### entities / screenshot_entities
Deduplicated named entities (`entity_type` in
tool/technology/company/framework/...) with a per-screenshot join row
carrying `confidence`, `rationale`, and the `rule_id` that produced it.

### tags / screenshot_tags
Deduplicated tag names (domain classifications) with the same
confidence/rationale/rule_id lineage as entities, plus
`operator_assigned` to distinguish system-assigned tags from ones the
operator added by hand.

### collections / collection_items
Operator-defined groupings. A screenshot may belong to any number of
collections.

### notes
Operator-authored free text tied to a screenshot, with `created_at`/
`updated_at`. Never merged into `raw_ocr_text` or `corrected_ocr_text`.

### prompt_templates
Operator-saved prompt templates (via "Save as Template" in Prompt Lab),
distinct from the built-in mode instructions in
`config/prompt_templates.json`.

### generated_prompts
Every generated prompt is persisted: `mode`, `objective`,
`screenshot_ids` (JSON array), full rendered `content`, `created_at`.

### processing_events
Append-only audit log. `screenshot_id` is nullable (scan-level events use
`NULL`). Event types include `DISCOVERED`, `PROCESSED`, `OCR_RERUN`,
`OCR_CORRECTED`, `OCR_MARKED_UNUSABLE`, `DUPLICATE_SKIPPED`,
`REJECTED_PATH_TRAVERSAL`, `NOTE_ADDED`, `SCAN_COMPLETE`.

### settings
Simple key/value mirror table (the authoritative settings live in
`config/settings.json`; this table is available for runtime-only state
that shouldn't round-trip through the JSON file).

## screenshots_fts (FTS5)

Columns: `title`, `summary`, `raw_ocr_text`, `corrected_ocr_text`,
`tags_text`, `entities_text`, `notes_text`, `author_text`. Kept in sync
by triggers described in `ARCHITECTURE.md` -- never written to directly
by application code.

## Every derivative artifact preserves

Per the project's primary laws, every table that derives from a
screenshot (`ocr_extractions`, `ocr_revisions`, `screenshot_tags`,
`screenshot_entities`, `notes`, `generated_prompts`) is linked back to
`screenshots.id`, and through it to `sha256`, `original_path`,
`processing_status`, and timestamps -- so lineage from any derivative
back to its source evidence is always reconstructable.
