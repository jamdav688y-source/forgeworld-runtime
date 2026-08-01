# Privacy Boundary

## Network

- Flask binds to `127.0.0.1` only (`config/settings.json: host`). It is
  never started on `0.0.0.0`. `app.py` reads `host`/`port` from settings
  at startup rather than hardcoding a public bind address.
- `cloud_uploads_enabled` defaults to `false` and nothing in this
  codebase makes an outbound network call for OCR, classification,
  summarization, or search. `requests` is present only as an approved
  dependency for a possible future explicitly-authorized integration --
  it is not called anywhere in this cycle.
- `semantic_search_enabled` defaults to `false`; `embeddings.py` imports
  no embedding/vector library.

## Local data boundary

- Original screenshots are read-only from the app's perspective: OCR
  operates on an in-memory derivative (`ocr._build_derivative`), never on
  the file at `original_path`. Verified by
  `tests/test_indexer.py::test_ingest_preserves_original_file_unchanged`.
- No image binary is stored inside SQLite. Only bounded JPEG previews are
  cached to `runtime/previews/`, capped at `max_preview_dimension` pixels.
- All scan targets are validated against approved source directories
  (`indexer.resolve_within_source`) before any file is read; the app
  rejects any path that resolves outside the declared source root
  (`PathTraversalError`), regardless of symlinks or `..` segments.
- OCR text is treated as untrusted input: `execute_ocr_text` defaults to
  `false`, and no OCR output is ever passed to `eval`, `exec`, a shell,
  or a template-rendering context that would execute it. It is only
  ever displayed, stored, or included verbatim in generated text output.

## Exports

- Exports are written only to `runtime/exports/` on local disk. Nothing
  is uploaded. Every export explicitly carries source hashes, paths, and
  status so a human can audit exactly what left the "sources of record"
  and where it went (a local file the operator controls).
- Original image files are included in an export only if the operator
  explicitly selects that option (not implemented as a default in any
  export kind in this cycle).

## Operator device hardening (documented, not enforced by the app)

- Run `termux-setup-storage` once so `~/storage/shared` is the only
  filesystem surface probed; the app never scans the whole device.
- Recommended: Android Settings -> Apps -> Termux -> Battery ->
  Unrestricted, so bounded OCR batches aren't killed mid-batch. This is
  a suggestion in the UI/docs, not something the app can set for you.
- `termux-wake-lock` / `termux-wake-unlock`: the app does not itself
  acquire a wake lock (see `KNOWN_LIMITATIONS.md`); if you script a wake
  lock around a long OCR batch, always release it afterward.
