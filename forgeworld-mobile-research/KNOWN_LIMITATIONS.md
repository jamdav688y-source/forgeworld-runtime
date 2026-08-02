# Known Limitations

## Environment mismatch at build time

This project was built and tested inside a Linux cloud dev container
attached to the `forgeworld-runtime` GitHub repo, not inside Termux on
the target Android phone. See `VALIDATION_REPORT.md` for exactly what
was and wasn't exercised. The most likely on-device surprises:

- Package install friction under Termux's Python 3.13 build (even for
  the approved, non-compiled dependency list).
- Tesseract binary path/version differences (Termux `pkg install
  tesseract` vs. `apt-get install tesseract-ocr` used here).
- Real screenshot images (dense UI chrome, low contrast, small text)
  will OCR and classify very differently than the synthetic test images
  used during development.

## Classification is keyword-based, not semantic

`indexer.classify_text()` does literal substring matching against
`config/classification_rules.json`. It will miss paraphrased or
differently-worded content, and can false-positive on incidental word
matches (e.g. a screenshot that merely mentions "agent" in an unrelated
sense still gets the `agent_systems` tag). This is intentional per the
project's "deterministic and inspectable" requirement -- every tag
carries its triggering `rule_id` and `rationale` precisely so these
false positives are auditable and correctable, not hidden. Operators can
edit `config/classification_rules.json` to tune recall/precision, or
override tags manually (UI supports viewing rationale; manual tag
edit/delete API is not yet wired into the client, only the data model
supports `operator_assigned`).

## OCR confidence and accuracy

Tesseract's `--psm 6` default assumes a single uniform block of text.
Screenshots with multi-column layouts, overlapping UI elements, or
stylized fonts will OCR worse than plain paragraphs. `ocr_confidence` is
Tesseract's own per-word confidence average and should be read as a
weak signal, not a correctness guarantee -- this mirrors the project law
that "search relevance does not imply correctness or authority."

## Semantic search is intentionally absent

`embeddings.py` is a disabled stub by design (see
`ARCHITECTURE.md` / the project's Semantic Search Boundary). FTS5
keyword/phrase search is the only retrieval mechanism in this cycle.
Multi-word conceptual queries that don't share vocabulary with the
source text (e.g. searching "governed autonomy" against a screenshot
that only says "human-in-the-loop control") will not match. This is a
known, accepted gap until FTS5 is used in real operation long enough to
measure whether it's actually insufficient.

## No wake-lock management

`ocr.py`/`indexer.py` do not call `termux-wake-lock` or
`termux-wake-unlock` themselves -- the directive asks the *operator* to
manage this around long batches, and the app has no Termux:API
dependency for core operation. If you script a wake lock around a scan,
you are responsible for releasing it; the app doesn't know it was taken.

## Bounded polling is wired in, but unproven under real load; scheduled scan is a stub

`watcher.BoundedPoller` is now wired into `app.py`: toggling
`bounded_polling_enabled` in Settings starts/stops it, and
`/api/polling/start` / `/api/polling/stop` control it directly. It is
still off by default and has not been run for an extended period to
validate battery/memory behavior on a real device. Scheduled scan
(Termux:API-triggered) remains explicitly out of scope for this cycle
(`scheduled_scan_enabled` stays `false`; no Termux:API code exists).

## Concurrent OCR rerun/correct on the same screenshot can lose an update

Two simultaneous requests to rerun or correct OCR on the *same*
screenshot (e.g. a double-tap) can race on the final `UPDATE`, and the
second write silently wins. Scan-level concurrency is guarded (see
`VALIDATION_REPORT.md`'s Stabilization Sprint section), but this
narrower, much less likely race was deliberately left undefended rather
than adding per-resource locking for a single-operator tool. See
`VALIDATION_REPORT.md` for the two documented ways to close this if it
ever matters in practice.

## UI is a functional MVP, not a polished client

`static/app.js` is vanilla JS with no build step, covering every
required tab and control from the directive (dashboard stats, library
grid + detail modal, search with filters, collections CRUD, prompt lab
with all 15 modes, ingestion controls, settings editor, system status).
It has not been visually verified in a real mobile browser in this
environment (see `VALIDATION_REPORT.md`) -- expect rough edges in
layout/spacing on first real device use, even though the underlying API
calls were verified via `curl`.

## Cancellation is coarse-grained

The directive asks for Start/Pause/Resume/"Cancel After Current Item"
controls in Ingestion. The backend (`indexer.scan`) is a synchronous,
batch-bounded loop invoked per `/api/scan` call -- there is currently no
in-flight pause/resume/cancel signal into a running scan; the bounding
mechanism is the batch-size cap (`max_initial_batch`/`max_normal_batch`),
not an interruptible job. A truly cancellable background job queue was
judged out of scope for this cycle given the "one Flask process, no
extra background daemon" constraint, but is a reasonable next
enhancement if scans grow large enough to need mid-batch cancellation.
