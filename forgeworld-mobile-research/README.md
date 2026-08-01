# ForgeWorld Mobile Research Companion

A private, offline-first research companion for screenshots: discovers
screenshots in approved directories, OCRs them locally with Tesseract,
classifies them with deterministic rules, indexes them for full-text
search, and lets you build source-grounded prompt packages and export
packets for other tools (Codex, Claude Code, ChatGPT, NotebookLM,
LinkedIn, cinema/RPG design, etc).

This is the mobile knowledge-ingestion and institutional-memory layer of
ForgeWorld. It is not a general screenshot organizer, and it makes no
cloud calls unless explicitly enabled in a later cycle.

## Status

This project was built and tested inside a Linux dev container (Python
3.11, Flask, Pillow, pytesseract, Tesseract 5.3) to validate the full
pipeline end-to-end (schema, FTS5 sync, OCR, classification, search,
prompts, exports, API routes). It has **not yet been run inside Termux
on the target Android phone**, so device-specific paths
(`~/storage/shared/...`), `termux-setup-storage`, and
`termux-wake-lock`/`termux-wake-unlock` are implemented per spec but
unverified on-device. See `VALIDATION_REPORT.md` and
`KNOWN_LIMITATIONS.md`.

## Setup (Termux)

```bash
termux-setup-storage
cd ~/forgeworld-mobile-research
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pip check
pkg install tesseract   # if not already installed
python app.py
```

The app binds to `127.0.0.1:5055` only. Open that address in a mobile
browser on the same device.

## First run

1. Open the **Ingestion** tab.
2. Tap **Probe Sources** -- this checks the candidate screenshot
   directories in `config/source_paths.json` and enables the ones that
   actually exist on this device, plus a bounded (`maxdepth 5`) search
   under `~/storage/shared` for any directory with "screenshot" in its
   name.
3. Enable the sources you want scanned.
4. Tap **Start Scan** (bounded to `max_initial_batch` / `max_normal_batch`
   from `config/settings.json`).
5. Browse results in **Library**, search in **Search**, and build prompt
   packages in **Prompt Lab**.

## Running tests

```bash
python -m pytest tests/
```

## Primary laws (see full text in the project directive / doctrine)

- Original screenshots are immutable source evidence -- never modified,
  renamed, moved, or deleted.
- OCR text is an extraction and may contain errors; corrections are
  stored as revisions, never overwriting the raw OCR.
- Summaries are machine-generated interpretations
  (`SYSTEM_EXTRACTIVE_SUMMARY`), not verified fact.
- Tags/entities are classifications with recorded confidence, rationale,
  and triggering rule -- not validated truth.
- Unknown information stays UNKNOWN; nothing claims understanding it
  doesn't have.

See `ARCHITECTURE.md`, `DATA_MODEL.md`, `PRIVACY_BOUNDARY.md`,
`VALIDATION_REPORT.md`, and `KNOWN_LIMITATIONS.md` for details.
