# Validation Report

Built and validated in a Linux dev container (`forgeworld-runtime` repo,
cloud session), **not** on the target Android/Termux device. This report
states exactly what was and wasn't verified, per the project's law that
nothing should claim more understanding/verification than it has.

## Environment used for validation

- Python 3.11.15 (target device spec: Python 3.13 -- not tested on 3.13)
- Flask (latest, installed fresh), Pillow (latest, installed fresh)
- pytesseract (latest, installed fresh)
- Tesseract 5.3.4 via `apt-get install tesseract-ocr` (target device:
  5.5.2 via Termux `pkg` -- close but not identical build)
- SQLite 3.45.1 (bundled with Python 3.11 here; target device: 3.53.2 --
  FTS5 support confirmed present in both)
- No Termux, no Android storage, no `termux-setup-storage`,
  `termux-wake-lock`, or Termux:API in this environment.

## What was actually exercised

1. **Schema + FTS5 sync** (`tests/test_database.py`, manual smoke test):
   insert/update/delete on `screenshots` correctly propagates into
   `screenshots_fts`; tag/entity/note changes correctly recompute the
   aggregated FTS columns. `sha256` UNIQUE constraint verified.
2. **OCR pipeline** (`ocr.py`, manual smoke test): ran real Tesseract
   against a generated PNG containing rendered text and got a `PASS`
   result with confidence and normalized text. Also verified graceful
   `FAILED` degradation when Tesseract is missing (no crash, informative
   `error_message`, valid `ocr_extractions` row still written).
3. **Ingestion pipeline** (`tests/test_indexer.py` + live scan against
   `/api/scan`): SHA-256 hashing, path-traversal rejection, preview
   generation, dedupe-on-rehash, idempotent rescan (0 new / N duplicate
   on second scan of the same directory), and confirmed byte-identical
   original file before/after ingestion.
4. **Deterministic classification** (`tests/test_indexer.py`): keyword
   rules from `config/classification_rules.json` produce tags/entities
   with recorded `rule_id`/`rationale`/`confidence`.
5. **Search** (`tests/test_search.py` + live `/api/search`): keyword,
   phrase, tag-filter, and min-confidence-filter queries all returned
   correct result sets; operator-typed FTS5 operator syntax (`OR`,
   unterminated quotes) verified not to raise.
6. **Full Flask app, live** (`app.py` run with `python app.py`,
   exercised via `curl`): `/`, `/api/dashboard`, `/api/sources`,
   `/api/sources/update`, `/api/scan`, `/api/library`, `/api/search`,
   `/api/collections` (create + add items), `/api/prompts/generate`,
   `/api/exports/{markdown,json,csv,notebooklm}`, `/previews/<hash>.jpg`,
   `/originals/<id>`, `/api/screenshots/<id>/notes`,
   `/api/screenshots/<id>/ocr/correct` all returned expected
   `200`/payloads in a live end-to-end run against two real generated
   screenshot images.
7. `python -m pytest tests/` -- 13/13 passing.
8. `python -m pip check` -- no broken requirements with the pinned
   `requirements.txt` package set (Flask, Pillow, pytesseract, watchdog,
   python-dateutil, requests, pytest only; no Pydantic/Rust/compiled
   deps required).

## What was NOT validated (must be verified on-device before relying on it)

- Behavior under real Termux/Android: `~/storage/shared` paths,
  `termux-setup-storage` permission flow, Termux `pkg install
  tesseract`, and whether `pytesseract`/`Pillow` wheels install cleanly
  under Termux's Python 3.13 build (the directive already flags that
  Pydantic failed there for Rust/Maturin reasons; Pillow/pytesseract are
  pure-C/pure-Python and much more likely to be fine, but this has not
  been confirmed on this specific phone).
- Real screenshot content (UI screenshots, terminal captures, social
  posts) -- validation used synthetically rendered text on blank
  backgrounds, not actual phone screenshots, so OCR accuracy and
  classification-rule recall on real-world images is unmeasured.
- The mobile browser UI (`templates/index.html` / `static/app.js`) was
  only checked by reading the served HTML/JS and confirming the API
  contract it depends on; it was not opened in an actual mobile browser
  or Chromium and clicked through, since this container has no display
  bound to the running server's expected mobile viewport flow beyond
  what the `curl` checks above cover.
- Battery, memory, and elapsed-time measurements for OCR batches
  (required before ever enabling semantic search, per the project's
  Semantic Search Boundary) -- not measured, since that requires the
  real device under real load.
- WAL-mode behavior under Android's stricter storage/process lifecycle
  (e.g. the OS killing the app mid-scan) -- the scan loop commits after
  each `ingest_file` call (via `Database.cursor()`'s per-call commit), so
  a kill mid-scan should leave the database consistent up to the last
  completed file, but this has not been tested under an actual forced
  process kill.

## Recommendation

Treat this as a validated *implementation* of the specified architecture,
not a validated *on-device deployment*. Run the "First run" steps in
`README.md` on the actual phone before trusting it with real screenshots,
and update this report with on-device results.
