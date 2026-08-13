# UX_SPEC.md — Next Right Move

**Role:** Experience Designer
**Status:** Approved for implementation

## 1. Design intent

The interface should feel like a quiet notebook, not a diagnostic form.
Target reaction: **"I can think through this."** Explicitly avoided
reactions: "software is evaluating me," "this looks like an AA app," "this
looks like a hospital intake form," "this looks like a chatbot."

## 2. Visual language

- Warm, low-saturation palette (parchment / deep sage-green), not clinical
  white-and-blue and not recovery-brand orange/blue.
- Generous whitespace, rounded corners (`16px`), no hard edges, no
  drop-shadows that read as "cards to be evaluated."
- System font stack only — no web fonts, no CDN, no layout shift from font
  loading, works fully offline.
- No avatars, no chat bubbles, no typing indicators — this is a form the
  user fills for themselves, not a conversation with an agent.
- `prefers-color-scheme: dark` supported natively via CSS custom
  properties; no manual toggle needed for v1.

## 3. Layout and breakpoints

- Mobile-first, single column, max content width `34rem` centered — reads
  identically on a 360px phone and a desktop browser window.
- Verified minimum target width: **360px** (common low-end Android
  viewport). No horizontal scrolling at any width in manual testing.
- Bottom-fixed navigation bar (Back / Skip / Next) stays reachable
  one-thumb on tall phones; respects `env(safe-area-inset-bottom)` for
  devices with gesture bars.
- Touch targets: all interactive controls are at least 44px tall.

## 4. Cognitive load rules

- One question per screen. No screen shows more than one primary text
  input plus its label and a one-line hint.
- No progress percentage or countdown — only a plain "Step N of 7" label,
  which informs without pressuring.
- No word counts, quality scores, or "good answer" feedback of any kind.
- Optional example chips on the Options screen are collapsed behind a
  `<details>` disclosure by default, so they never crowd the primary task
  of writing your own options first.

## 5. Navigation model

- **Next** — saves the current field and advances.
- **Skip** — clears the current field for this session and advances
  without requiring input. Skip is available on every step; nothing is
  ever mandatory.
- **Back** — saves the current field and returns to the previous step (or
  to the intro from step 1). Back never discards data.
- Direct URL deep-linking into the middle of the flow is intentionally not
  supported — the flow always starts at the last screen the user was on
  in this browser session (see PRIVACY_MODEL.md for what "session" means),
  or at `intro` for a first visit.

## 6. Error states

There is no validation to fail — every field accepts anything, including
nothing. The only "error-like" states handled explicitly:

- **Empty submission** → treated identically to Skip. No red text, no
  blocking.
- **Very long input** → `maxlength` set generously (2000 chars for
  paragraphs, 200 for a single option) to prevent runaway layout issues,
  not to police the user's writing.
- **sessionStorage unavailable** (e.g. locked-down private browsing) →
  the app degrades to in-memory-only state for that page load; nothing
  throws, nothing blocks the flow. Documented in PRIVACY_MODEL.md.
- **Service worker registration fails** → caught silently; the page that
  already loaded keeps working normally, it just won't be available
  offline next time.

## 7. Accessibility

- Every screen's `<h1>` receives programmatic focus on screen change, so
  screen-reader users hear the new question immediately and keyboard
  users land in a predictable place.
- Skip link to main content for keyboard users.
- All interactive elements are real `<button>`, `<input>`, `<textarea>`,
  `<label>` elements — no click-handlers on generic `<div>`s.
- Visible focus outlines (`:focus-visible`) using a high-contrast color
  independent of the accent color, so focus is visible in both themes.
- Color is never the only signal — the "(skipped)" label is text, not a
  color change.
- `aria-live="polite"` on the option list and toast so additions/removals
  and confirmations are announced without interrupting typing.

## 8. Classroom usability notes

- No instructor-facing mode, no shared device concerns beyond
  **Clear session**, which is deliberately one tap plus one confirmation
  — fast enough to reset between students, deliberate enough to avoid
  accidental data loss mid-use.
- The intro screen's reassurance list ("Nothing you type leaves this
  device," "No account, no login, no tracking") is written for a first-time
  user with zero context, per the mission's design constraint.
- Non-clinical disclaimer is present on the intro screen, not buried in a
  separate settings page, since this may be the only screen some users
  read carefully.
