# PRIVACY_AUDIT.md — Next Right Move

**Role:** Privacy / Governance Reviewer
**Authority:** BLOCK authority over release
**Audit date:** 2026-08-13
**Scope audited:** `index.html`, `styles.css`, `app.js`, `manifest.json`,
`service-worker.js`, `assets/` (2 PNG icons, generated locally, no
third-party source). `tests/adversarial.js` is excluded from this scope —
it is a developer-only Playwright script, never shipped or loaded by the
app, and is not reachable from any page a user visits. It was re-scanned
separately anyway: its only `http://` references are to
`http://localhost:8080`, the local test server address, never a
third-party host.

## Method

1. Full manual read of every source file (all five text files are small
   enough to read in full; no minified or generated JS ships in the app).
2. Pattern search across the entire app directory for network primitives
   and known telemetry signatures:
   `fetch(`, `XMLHttpRequest`, `http://`, `https://`, `analytics`, `gtag`,
   `sentry`, `beacon`, `websocket`, `localStorage`.
3. Manual trace of every code path that touches `sessionStorage` or
   creates a `Blob`/download, to confirm nothing external is reachable.
4. Manual verification of Clear Session against the storage keys it
   claims to remove.
5. Dependency check: `package.json` — none exists. No `node_modules`. No
   `<script src="https://...">`. No `@font-face` remote URLs. No CDN
   references anywhere.

## Findings

### Search result (step 2), verbatim

```
$ grep -rniE "fetch\(|xmlhttprequest|http://|https://|analytics|gtag|ga\(|sentry|beacon|websocket|localStorage" \
    --include="*.js" --include="*.html" --include="*.json" --include="*.css" .

./app.js:3: * No network calls. No analytics. State lives only in sessionStorage
./service-worker.js:50:      return fetch(event.request)
```

Only two matches:
- `app.js` line 3 is a comment, not code.
- `service-worker.js` line 50 is the single `fetch(...)` call in the
  entire codebase. It appears inside the service worker's `fetch` event
  handler, which only ever runs in response to the page requesting one of
  its **own same-origin files** (see `APP_SHELL` list in the same file).
  It is a cache-miss fallback to normal browser networking for the app's
  own assets — not an outbound call the application initiates on its own,
  and it never carries user-entered text (GET requests for static files
  only; the request objects passed through are the browser's own asset
  requests, never constructed from form data).

No occurrence of `localStorage`, `XMLHttpRequest`, any hardcoded
`http://`/`https://` third-party URL, or any analytics/telemetry
identifier anywhere in the app.

### Data path trace

| Path | Destination | Verdict |
|---|---|---|
| Text field → `input` event → `state` object | In-memory JS variable | Local only |
| `state` → `saveState()` | `sessionStorage` (same origin) | Local only, browser-destroyed on tab close |
| `state` → `Export as text` | Local `Blob` → `blob:` URL → OS file download | Local only, requires explicit user tap |
| App shell files → service worker `install` | Cache Storage (same origin) | Local only, contains no user data |
| Any field → any network request | **No such path exists in the code.** | N/A |

### Clear Session verification

Read `app.js` `#clear-confirm-btn` handler directly: it removes both
storage keys (`nrm_state_v1`, `nrm_screen_v1`) used anywhere in the app
(confirmed these are the *only* two storage keys the app ever writes, via
full-file read of every `sessionStorage.setItem`/`getItem` call site), and
resets in-memory state to defaults. No storage key is written anywhere
that Clear Session does not also remove.

### Dependency audit

No `package.json`, no build step, no bundler, no third-party JS library,
no web font service, no CDN. The two PNG icons in `assets/` were generated
by a local script from geometric primitives (no photos, no downloaded
assets, no embedded metadata beyond standard PNG chunks).

## Checklist result

| Requirement | Result |
|---|---|
| No account / login / name required | PASS |
| No remote database | PASS |
| No advertising | PASS |
| No behavioral analytics | PASS |
| No tracking pixels | PASS |
| No cloud AI dependency | PASS |
| No third-party telemetry | PASS |
| No recovery/sobriety scoring | PASS |
| No diagnostic inference | PASS |
| No automatic transmission of entered text | PASS |
| Local-only execution (no server-side logic) | PASS |
| Clear Session removes all app-written storage | PASS |
| Export requires explicit user action, local file only | PASS |

## Verdict

**PRIVACY AUDIT: PASS — no BLOCK issued.**

No accidental persistence, no hidden network path, and no telemetry of any
kind were found. Release is not blocked on privacy grounds.

## Residual notes (informational, not blocking)

- Standard mobile-keyboard autofill/spellcheck operates outside this app's
  control on any device (see PRIVACY_MODEL.md §7). This is host-OS/browser
  behavior, not something this codebase can or should override.
- sessionStorage persisting across a same-tab refresh (rather than being
  wiped on every navigation) is a deliberate UX trade-off, documented in
  PRIVACY_MODEL.md §2, not an oversight.
