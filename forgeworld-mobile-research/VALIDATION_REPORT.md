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
7. `python -m pytest tests/` -- 26/26 passing (see Stabilization Sprint
   section below for what was added in this cycle).
8. `python -m pip check` -- no broken requirements with the pinned
   `requirements.txt` package set (Flask, Pillow, pytesseract, watchdog,
   python-dateutil, requests, pytest only; no Pydantic/Rust/compiled
   deps required).

## Stabilization sprint (post-initial-build hardening)

A follow-up pass audited the initial build for defects via code inspection
plus a live smoke test, then fixed and re-verified everything found. Full
methodology and each fix's verification are in the corresponding modules'
docstrings/tests; this is the summary.

**Data integrity**
- **Fixed a real bug**: a screenshot whose row was inserted but whose
  OCR/classification never completed (process killed mid-`ingest_file`)
  used to be permanently stuck at `PENDING` -- a rescan saw the hash
  already existed and silently classified it `DUPLICATE` forever, so it
  never got OCR'd. Reproduced by directly inserting a `PENDING` row and
  rescanning, confirmed stuck, then fixed in `indexer.py` (`ingest_file`
  now resumes any `PENDING`/`FAILED` row instead of skipping it) and
  confirmed fixed the same way. Same fix covers a `FAILED` row from a
  prior OCR crash. Regression tests:
  `tests/test_indexer.py::test_interrupted_scan_resumes_stranded_pending_row`,
  `::test_interrupted_scan_resumes_failed_row`,
  `::test_already_processed_row_stays_duplicate` (confirms only
  unfinished rows resume, not already-`PROCESSED` ones).
- A race between two scans discovering the same new hash simultaneously
  (`sqlite3.IntegrityError` on the `UNIQUE(sha256)` insert) is now caught
  and falls through to the resume/duplicate path instead of crashing.

**Concurrency**
- `/api/scan` now holds a process-wide lock for the duration of a scan;
  a second concurrent scan request gets a clean `409` instead of racing
  the first scan's DB writes. Verified live (two scans fired back-to-back,
  second got 409 while the first completed normally) and in
  `tests/test_app.py::test_scan_returns_409_when_already_in_progress`.

**API reliability**
- Every route now returns JSON on error instead of Flask's default HTML
  error page: malformed JSON bodies, invalid numeric query params
  (`/api/library?limit=x`, `/api/search?min_confidence=x`,
  `/api/exports/<kind>?collection_id=x`), and any other unhandled
  exception, via three new `app.errorhandler`s in `app.py`. Verified live
  with `curl` for each case and in `tests/test_app.py`.
- `/api/settings` now type-coerces and validates incoming values against
  the `Settings` dataclass's declared types instead of blindly
  `setattr`-ing whatever JSON came in; invalid values are rejected with a
  `400` and a per-field reason, and nothing is partially saved.

**Security**
- `static/app.js` previously interpolated several fields straight into
  `innerHTML` without escaping: screenshot titles/filenames, search
  excerpts (which come from OCR'd image text via FTS5 `snippet()`), tag/
  entity names, and source paths. A crafted filename or OCR'd string
  could inject markup. All of these now go through `escapeHtml()`.

**Observability**
- Added a rotating file logger (`runtime/logs/app.log`, 2MB x 3 backups)
  wired into `config.py`, and log calls along the scan lifecycle
  (start/finish/lock-rejected), OCR outcomes (PASS/EMPTY/FAILED/TIMEOUT
  with timing), resume/duplicate/discovery events, and rejected input.
  Previously `runtime/logs/` existed but nothing ever wrote to it.
  Verified live: ran a scan and confirmed the full lifecycle appeared in
  `app.log`.

**User experience**
- Silent-failure click handlers (OCR correct/rerun/unusable, add note,
  create collection, search, ingestion actions) now surface errors to
  the operator instead of failing invisibly.
- Scan summaries now report a `resumed_count` alongside new/duplicate/
  skipped/error counts, so a resumed interrupted scan is visible in the
  UI, not indistinguishable from a normal duplicate.
- `watcher.BoundedPoller` (previously fully implemented but never
  imported anywhere) is now wired into `app.py`: toggling
  `bounded_polling_enabled` in Settings actually starts/stops it, plus
  explicit `/api/polling/start` and `/api/polling/stop` endpoints.

**Incidentally found and fixed while testing the above**
- `Settings.save()`, `save_source_paths()`, and related `config.py`
  loaders took their file path as a default argument bound at *function
  definition* time, not call time -- so monkeypatching the module-level
  path constant in a test had no effect, and (more importantly) it meant
  every `Settings` instance's `.save()` always wrote to the one real
  `config/settings.json` regardless of what settings object it was
  called on. Changed to a `None`-sentinel pattern that resolves the path
  dynamically at call time. This was caught because an early version of
  the new `tests/test_app.py` fixture silently corrupted the real
  `config/settings.json` during a test run before this fix -- restored
  from git and reproduced clean afterward.
- `/api/scan` checked "any sources enabled" before checking the
  concurrency lock, so a request could get a `400` instead of a `409`
  when no sources were configured. Reordered so the lock check always
  wins first.

## Not fixed -- documented as accepted / needs a design decision

- **Lost-update race on concurrent OCR rerun/correct for the same
  screenshot**: two simultaneous requests to `/api/screenshots/<id>/ocr/
  rerun` (or one rerun racing one correction) can both read-then-write
  `screenshots.raw_ocr_text`/`corrected_ocr_text`, and the second write
  wins silently. Given this is a single-operator mobile tool where that
  requires deliberately double-tapping the same button on the same
  screenshot, this was judged not worth a per-resource locking mechanism
  in this sprint (would add real complexity for a very unlikely
  scenario). If it becomes a real problem, the fix is either an
  optimistic-concurrency `updated_at` check on the `UPDATE`, or a
  per-screenshot lock dict alongside the existing scan lock.

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
  each SQL statement (via `Database.cursor()`'s per-call commit), and a
  file whose row exists but never reached `PROCESSED` is now correctly
  resumed on the next scan (see Stabilization Sprint above, verified by
  directly inserting a stranded `PENDING` row and confirming a live
  `/api/scan` call resumes and completes it). What's still unverified is
  an actual forced OS process kill mid-write on the real device -- this
  test simulated the *symptom* (a stranded row) rather than the kill
  itself, which behaves differently under Android's process lifecycle
  than a clean container.
- Restart persistence was re-verified live in this sprint: scanned 3
  screenshots, killed the server process, restarted it, and confirmed
  `/api/dashboard` still reported all 3 -- but still only in this
  container, not on-device.

## Recommendation

Treat this as a validated *implementation* of the specified architecture,
not a validated *on-device deployment*. Run the "First run" steps in
`README.md` on the actual phone before trusting it with real screenshots,
and update this report with on-device results.
