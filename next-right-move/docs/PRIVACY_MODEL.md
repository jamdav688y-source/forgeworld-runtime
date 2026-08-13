# PRIVACY_MODEL.md — Next Right Move

**Role:** Privacy / Governance Reviewer
**Authority:** This role has BLOCK authority over release. A failed privacy
requirement blocks release regardless of functional completeness.

## 1. What data exists, and where it lives

Next Right Move stores exactly one thing: the text you type into the seven
steps and the "Run it again" friend comparison, plus which screen you were
last on. It is stored **only** in the browser's `sessionStorage` for the
page's origin, under two keys:

| Key | Contents |
|---|---|
| `nrm_state_v1` | JSON object: `fact`, `story`, `urge`, `knowledge`, `options` (array), `costOptionIndex`, `costNote`, `nextMove`, `friendAdvice` |
| `nrm_screen_v1` | Name of the current screen (e.g. `"fact"`), so a refresh resumes where you left off |

**Nothing else is written.** No `localStorage`, no cookies, no
IndexedDB, no server-side database (there is no server component at all —
this is a static file set).

## 2. Why `sessionStorage` and not `localStorage`

`sessionStorage` is scoped to the browser tab and is **automatically
destroyed by the browser when that tab or app instance closes** — no code
of ours has to run for it to be gone. This gives a real, browser-enforced
"this doesn't outlive my session" guarantee that `localStorage` (which
persists indefinitely) does not.

Trade-off, stated plainly: a refresh of the same tab does **not** lose your
progress (sessionStorage survives reloads within the same tab), but closing
the tab, closing the installed PWA, or force-closing the browser task does
lose it, with no prompt. This is intentional and matches the "session" in
the product's name. See README.md "Refresh vs. close behavior" for the
user-facing explanation.

## 3. Clear Session — exact behavior

The "Clear session" control (top of every screen) opens a confirmation
dialog. On confirm, the app:

1. Calls `sessionStorage.removeItem("nrm_state_v1")`
2. Calls `sessionStorage.removeItem("nrm_screen_v1")`
3. Resets the in-memory JavaScript state object to empty defaults
4. Returns to the intro screen

After this, no trace of the session's text remains anywhere the app
controls — not in memory, not in storage. This is independent of the
Cache Storage used for offline app-shell files (see §5) — that cache holds
only the application's own code/assets, never user-entered text.

## 4. Export — the only way data leaves the device

The "Export as text" button on the summary screen builds a plain-text
`Blob` in memory, creates a local `blob:` URL, and triggers a
browser-native file download via a temporary `<a download>` element. This:

- Does **not** use `fetch`, `XMLHttpRequest`, `navigator.sendBeacon`, a
  `<form>` submission, or any other network primitive.
- Never contacts any server, first-party or third-party.
- Produces a `.txt` file that lands wherever the browser/OS puts downloads
  — from that point on, it is a normal file the user controls, outside the
  app's data model.

This is the **only** path by which entered text can leave the device, and
it requires an explicit, single, user-initiated tap. Nothing is exported
automatically, on a timer, on blur, or on any other implicit trigger.

## 5. Offline caching (service worker) — what it stores and why it's not a privacy concern

`service-worker.js` caches the application's own static files (HTML, CSS,
JS, manifest, icons) in the browser's Cache Storage so the app loads with
no network connection after the first visit. It intercepts `fetch` events
the *page* makes for its *own same-origin assets* only.

It does **not**:
- Cache or transmit any form input, textarea content, or app state.
- Make any request the user or app didn't already trigger by loading a page
  or asset.
- Contact any origin other than the one the app is served from.

## 6. Explicit non-list — everything this app does not do

- No account creation, login, username, or name field anywhere.
- No remote database or backend server of any kind.
- No advertising, ad SDKs, or ad identifiers.
- No behavioral analytics, event tracking, or usage metrics.
- No tracking pixels, beacons, or third-party embeds.
- No cloud AI calls — all logic is static JavaScript running in the
  browser; there is no API key, no model endpoint, nothing to call out to.
- No third-party telemetry or crash reporting libraries.
- No recovery/sobriety scoring, streaks, or risk levels.
- No diagnostic or clinical inference performed on any input.
- No automatic transmission of entered text, ever, under any
  configuration.
- No dependencies at all — zero `npm` packages, zero CDN `<script>` or
  `<link>` tags. The entire app is four hand-written files plus two PNG
  icons.

## 7. Threat model notes for a shared classroom device

- Because state lives in `sessionStorage`, a student who forgets to hit
  "Clear session" but simply **closes the browser tab** has already had
  their data destroyed by the browser itself.
- A student who leaves the tab open and hands the device to the next
  person **has not** had it cleared — this is why Clear Session exists as
  an explicit, fast, always-available action, and why the README
  recommends making it part of classroom handoff routine.
- Browser autofill / spellcheck is native browser behavior outside this
  app's control; instructors relying on maximum discretion on a shared
  device should be aware standard mobile keyboards may suggest previously
  typed words regardless of what this app does with storage.
