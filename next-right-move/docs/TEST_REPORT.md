# TEST_REPORT.md — Next Right Move

**Role:** Adversarial Tester
**Authority:** Reports failures to integration authority; does not silently
repair them. (Note: two functional bugs found during this pass *were*
fixed before this report was finalized, by the integration authority, not
by the tester — see "Bugs found and resolved" below, kept visible rather
than erased from the record.)

## Method

Automated adversarial script (`tests/adversarial.js`) driving real Chromium
via Playwright against the app served statically on
`http://localhost:8080` (`python3 -m http.server 8080`, matching the
Termux launch method in README.md). 21 checks across 13 scenarios named in
the mission brief. Manual review supplemented the automated run for items
a script can't easily judge (visual calm, copy tone).

Run: `node tests/adversarial.js http://localhost:8080`

## Bugs found and resolved

Both were found by the automated pass on the first run, before any manual
fixing — recorded here rather than hidden, per this role's mandate not to
silently repair without disclosure.

### Bug 1 — Clear Session confirmation dialog was unclickable

**Symptom:** `Start`, and every other button, became unclickable after the
first page load in a fresh context in one run path; root cause traced to
the `#clear-dialog-backdrop` element.

**Root cause:** `styles.css` declared `.dialog-backdrop { display: flex; }`
for the confirmation dialog's backdrop. The element also carries the HTML
`hidden` attribute when closed. Because author CSS (`display: flex`) beats
the browser's built-in `[hidden] { display: none }` rule at equal
selector specificity, the backdrop stayed laid out and full-screen even
while `hidden`, silently intercepting taps meant for the page underneath.

**Fix:** Added an explicit `.dialog-backdrop[hidden] { display: none; }`
rule in `styles.css`. Verified the same pattern was already correctly
handled for `.step-nav[hidden]` elsewhere in the same file.

**Verification:** Full flow (start → all 7 steps → summary → clear
session → confirm) now completes without any unintended overlay.

### Bug 2 — Clear Session left a residual sessionStorage key

**Symptom:** After confirming Clear Session, `nrm_screen_v1` was
immediately re-written to `"intro"` by the subsequent `showScreen("intro")`
call, so `sessionStorage.getItem("nrm_screen_v1")` was not actually `null`
right after clearing — contradicting the literal claim in
`PRIVACY_MODEL.md` §3 that both keys are removed.

**Severity:** Low — the residual value (`"intro"`) contains no user
content, so this was not a data-exposure issue. It was a correctness gap
between documentation and behavior, which the Privacy/Governance role
treats seriously even when the content itself is inert.

**Fix:** Reordered `app.js`'s clear-session handler to explicitly remove
both storage keys again after `showScreen("intro")` runs, so the
post-condition matches the documentation exactly: both keys absent.

**Verification:** `sessionStorage.getItem("nrm_state_v1")` and
`sessionStorage.getItem("nrm_screen_v1")` are both `null` immediately after
confirming Clear Session, and remain absent after a subsequent reload.

## Full results (after fixes)

| # | Scenario | Result |
|---|---|---|
| 1 | Loads at 360px width, no external network requests | PASS |
| 2 | Loads at 360px width, no horizontal overflow | PASS |
| 3 | Empty input: Skip through all 7 steps reaches summary | PASS |
| 4 | Empty input: skipped fields render as "(skipped)", not blank/guessed | PASS |
| 5 | Very long input (5000 chars into a 2000-char field): truncates at limit, no layout break | PASS |
| 6 | Very long input: no horizontal overflow | PASS |
| 7 | Unexpected characters: `<script>` payload, emoji, newlines, tabs, quotes — no script execution | PASS |
| 8 | Unexpected characters: content still rendered faithfully as text (not stripped, not corrupted) | PASS |
| 9 | Refresh mid-flow: resumes on the same step | PASS |
| 10 | Refresh mid-flow: in-progress field text survives | PASS |
| 11 | Back navigation: preserves the field just left | PASS |
| 12 | Rapid tapping (15x on Next in quick succession): lands on a valid known screen, no crash, no duplicate state corruption | PASS |
| 13 | Options: whitespace-only entry is not added as an option | PASS |
| 14 | Options: valid entries add correctly | PASS |
| 15 | Options: remove works and re-indexes correctly | PASS |
| 16 | Clear session: returns to intro screen | PASS |
| 17 | Clear session: both sessionStorage keys actually removed | PASS (after Bug 2 fix) |
| 18 | Clear session: data does not resurrect after a reload | PASS |
| 19 | Run it again: "what I'm telling myself" reflects story/urge/next-move | PASS |
| 20 | Run it again: friend comparison reflects the user's own friend-voice text | PASS |
| 21 | Orientation change (360×740 → 740×360): no horizontal overflow | PASS |
| 22 | Offline operation: after first load, page reloads successfully with the network fully disabled (`context.setOffline(true)`) | PASS |
| 23 | Accessibility: focus moves to the new step's heading on every screen change | PASS |

**23/23 automated checks pass.**

## Manual checks (not easily scriptable)

- **Small screens (~360px):** confirmed visually in a 360×740 viewport —
  no clipped text, no overlapping controls, bottom nav bar stays reachable.
- **Visual tone:** reviewed against UX_SPEC.md's "I can think through
  this" / not-clinical goal — no red alert colors, no scored feedback, no
  chat-bubble UI.
- **PWA installability:** `manifest.json` parses as valid JSON
  (`python3 -m json.tool`), all four required icon entries resolve to
  real files that return HTTP 200, `start_url` and `scope` are
  same-origin relative paths.
- **Service worker registration:** confirmed via
  `navigator.serviceWorker.ready` resolving after first load, and the
  offline reload check (scenario 22) which would fail if the worker
  weren't controlling the page.

## What this pass does not cover

- Real Android/Termux device testing (this environment has no physical
  device or emulator attached). Chromium desktop with a mobile viewport
  was used as the closest available proxy — see RELEASE_REPORT.md for the
  resulting scope note.
- Screen-reader software testing (VoiceOver/TalkBack) — only programmatic
  focus management and semantic markup were verified, not actual
  screen-reader output.
- Long-running multi-hour offline sessions or storage-quota exhaustion.

## Verdict

No open functional defects. No privacy findings (see PRIVACY_AUDIT.md,
which is the authoritative privacy sign-off). This role does not block or
approve release on its own — it hands this report to the integration
authority.
