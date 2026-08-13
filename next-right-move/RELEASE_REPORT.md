# RELEASE_REPORT.md — Next Right Move

**Role:** Release Engineer
**Mission:** NEXT-RIGHT-MOVE-001
**Date:** 2026-08-13

## Authority flow followed

```
BUILD → REVIEW → TEST → PRIVACY AUDIT → INTEGRATION → RETEST → RELEASE CANDIDATE
```

- **Build:** `index.html`, `styles.css`, `app.js`, `manifest.json`,
  `service-worker.js`, `assets/icon-{192,512}.png` implemented per
  `docs/PRODUCT_SPEC.md` and `docs/UX_SPEC.md`.
- **Test:** `tests/adversarial.js` run against a live local server
  (23 automated checks — see `docs/TEST_REPORT.md`). First run found 2
  real bugs (an unclickable dialog overlay from a CSS `[hidden]`
  specificity conflict, and a residual sessionStorage key after Clear
  Session). Both were fixed in `styles.css` and `app.js` and re-verified
  by a second full test run, which passed 23/23.
- **Privacy audit:** Full source read plus pattern search across every
  file for network/telemetry signatures. Result: **PASS, no BLOCK
  issued.** Full detail in `docs/PRIVACY_AUDIT.md`.
- **Integration:** All pieces verified together — served as one static
  site, manifest validated, service worker confirmed controlling the
  page and serving it offline.
- **Retest:** Post-fix test run is the one recorded as the final result
  in `docs/TEST_REPORT.md` (23/23 pass).

No privacy requirement failed. No critical functional test failed after
fixes. Release is not blocked.

**Update 2026-08-13 (launch recovery):** a local-server launch failure
(`/index.html` 404 because the server's document root was one directory
too high) was diagnosed and fixed, and a self-locating launcher
(`start-next-right-move.sh`) was added so it can't recur regardless of
invocation directory. This was an operational/launch issue, not an
application defect — no functional or privacy regression was found. Full
detail, including the honest breakdown of what could vs. couldn't be
verified from this non-physical runtime, is in `docs/LAUNCH_RECOVERY.md`.

## Final validation checklist

| Item | Status |
|---|---|
| Loads on mobile (360px viewport tested) | ✅ |
| Usable at ~360px width, no horizontal overflow | ✅ |
| No login required | ✅ |
| No network dependency after installation/cache | ✅ (verified with network fully disabled) |
| No analytics | ✅ |
| No hidden remote calls | ✅ (full source scan, see PRIVACY_AUDIT.md) |
| Navigation works (Next/Back/Skip) | ✅ |
| State model works (7-step flow, options list, summary) | ✅ |
| RUN IT AGAIN works | ✅ |
| CLEAR SESSION actually clears state | ✅ (fixed during testing, then verified) |
| Refresh behavior is documented | ✅ (README.md "Refresh vs. close") |
| PWA manifest validates | ✅ (valid JSON, correct icon/start_url/scope fields) |
| Offline behavior tested | ✅ (Playwright `context.setOffline(true)` reload test) |
| Privacy audit passes | ✅ |
| README contains exact Termux commands | ✅ |
| App contains a non-clinical disclaimer | ✅ (intro screen, and README) |
| No unrelated project files were modified | ✅ (see below) |

## Scope note: real-device testing

This build environment has no attached Android device or emulator.
Functional and layout testing used Chromium (desktop) with a 360×740
mobile viewport as the closest available proxy, plus manual review against
`docs/UX_SPEC.md`. The HTML/CSS/JS used are all broadly-supported web
platform features (`sessionStorage`, Service Worker, `<details>`, CSS
custom properties, flexbox) with no browser-specific APIs, so real-device
behavior is expected to match, but has not been physically confirmed on a
Termux/Android device by this build process. Recommend a quick manual
smoke test on an actual phone before wide classroom use.

## Confirmation: no unrelated work touched

This build created exactly one new top-level directory,
`next-right-move/`, inside the existing repository. Verified via `git
status` that no other tracked file in the repository was modified,
renamed, or deleted.

## Release manifest

Repository-relative paths and SHA-256 checksums of every shipped file, for
integrity verification after transfer to a phone or a static host:

```
04bedcb26c11f0371599278cc5751cfe8ab8069c77ebc8a6560286cb8213f67f  README.md
df09e44922323cf904e992540edffafc88b3419556e0164bbfe771e1d33f3f94  app.js
43d29673603c49c5049c1d805b6a51e432754af3064b583c08dc9605bd23e676  assets/icon-192.png
1436784b3644a6572cc432ec1fb1b901bdc6af7e15b8935b746bbccfdeec47c9  assets/icon-512.png
7483a980e40dd27765f8ca38a245cd37c46d6692cb95464df851ab2da9f18f71  docs/PRIVACY_AUDIT.md
6dfc2a63c977813f3403efec0b10d1ed24c433f405e4f14f783c7ad452ac5bd7  docs/PRIVACY_MODEL.md
374c4861621b7b24271e16e04ef8c9f724367492f754e49a293278807ac10438  docs/PRODUCT_SPEC.md
9252111733a9371b9001037457967149fb673f90950f23fe20196bada6b43848  docs/TEST_REPORT.md
b7294a96c267ccb9430ee8f250575d7f5d986666878fea407833676bd5957d37  docs/UX_SPEC.md
c141701cad8f3d1b6172dea7d18c68f0bfcb5a4aa3921f002bcc96fb26468e97  index.html
a55717fdc0e806d496637b0fd600566d973946a35f6815b34da157ba3f074351  manifest.json
d971a82d2fa6ff60865d5b763fac7891abae6433c51de3d18a43a28b20214529  service-worker.js
e1d2c46cc55eb508b58d277a16466b528d11d1985254904ce1788f4375b8591b  styles.css
028111f6e29377abdf8380adddd62cd800626b42437d7cc230548c05977301aa  tests/adversarial.js
```

(Regenerate with `find . -type f -not -name RELEASE_REPORT.md | sort |
xargs sha256sum` from inside `next-right-move/`.)

## How to run it (Termux local demo)

```bash
cd next-right-move
python -m http.server 8080
# then open http://localhost:8080/index.html on the SAME phone
```

## How to make it a shareable classroom URL

Local demo only reaches the device it runs on. For other phones, deploy
the static folder to any static host (GitHub Pages, Netlify, Vercel,
Cloudflare Pages — no build step, no server code required) and share the
resulting URL. Full instructions in `README.md`.

## Release status

**CLASSROOM_READY**

No privacy blocks. No open functional defects. One scope caveat: verified
on desktop Chromium at mobile viewport sizes rather than a physical
Android device — recommend one manual phone smoke test before first
classroom use, per the scope note above.
