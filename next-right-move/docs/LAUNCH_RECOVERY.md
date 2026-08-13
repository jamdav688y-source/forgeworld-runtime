# LAUNCH_RECOVERY.md — Next Right Move

**Mission:** launch-failure repair (follow-up to initial release)
**Date:** 2026-08-13

## Important correction to the mission framing

The mission instructions asserted this session runs "directly on my
Android/Termux development environment" and later "the actual Android
device." **That is not what this session's evidence shows.** Direct
inspection returned:

```
$ uname -a
Linux vm 6.18.5-fc-v20 ... x86_64 GNU/Linux
$ ls /data/data/com.termux
No such file or directory
$ command -v termux-info
(not found)
```

This is a cloud Linux sandbox (an x86_64 VM), not a physical Android
device and not a Termux shell. It has no touchscreen, no on-screen
keyboard, and no `termux-open-url`. Per this mission's own instruction —
*"Do not fabricate a PASS"* — the touch-input, keyboard-obscuring, and
true on-device checks in Phase 5 are reported below as **not performed
here**, not as passing. Everything that genuinely could be verified from
this runtime was verified, and is reported as such.

## Phase 1 — Discovery (evidence)

```
pwd                                    -> /home/user/forgeworld-runtime
find / -maxdepth 6 -type d -iname "next-right-move*"
                                        -> /home/user/forgeworld-runtime/next-right-move   (only one)
find / -maxdepth 8 -type f -iname "index.html"
                                        -> .../next-right-move/index.html (plus unrelated Go
                                           stdlib test fixtures and one unrelated
                                           forgeworld-mobile-research template — not this app)
ss -tlnp | grep 8080                   -> nothing listening (no server was running
                                           in this session at discovery time)
ps -ef | grep http.server              -> no matches
```

No duplicate copies of the project exist anywhere on this filesystem.

## Phase 2 — Canonical project

```
CANONICAL_PROJECT=/home/user/forgeworld-runtime/next-right-move
```

Confirmed complete: `index.html`, `styles.css`, `app.js`, `manifest.json`,
`service-worker.js`, `assets/`, `docs/` (5 files including the prior
privacy audit and test report), `tests/`, `README.md`, `RELEASE_REPORT.md`
— matches the structure from the original build with no divergence,
because only one copy exists. `git log -- next-right-move` shows exactly
one commit, so there is no branching history to reconcile either.

## Phase 3 — 404 root cause

No server was running when this recovery session started, so the reported
404 could not be caught live — it was reproduced instead, byte-for-byte,
to confirm the mechanism:

```
$ python3 -m http.server 8081 --directory /home/user/forgeworld-runtime   # WRONG root: one level too high
$ curl http://localhost:8081/index.html
Error code: 404
Message: File not found.
```

This reproduces the user-reported error exactly. The same server, asked
for the correctly nested path, succeeds:

```
$ curl -o /dev/null -w "%{http_code}" http://localhost:8081/next-right-move/index.html
200
```

```
ROOT_CAUSE=A local HTTP server was serving from /home/user/forgeworld-runtime
(the repository root) instead of /home/user/forgeworld-runtime/next-right-move
(the project root). Because index.html lives one directory below the
server's actual document root, "GET /index.html" resolved to a
nonexistent path at that root and 404'd, even though the file exists and
the server process itself was healthy and responding — matching the
mission's own diagnostic note that localhost:8080 was reachable.
```

This is consistent with how the app was launched earlier in this project's
history: `python3 -m http.server 8080` run from the repository root rather
than from inside `next-right-move/`, or without an explicit `--directory`
flag pointing at it.

## Phase 4 — Repair

```
$ python3 -m http.server 8080 --directory /home/user/forgeworld-runtime/next-right-move
```

`--directory` was used specifically because it removes dependence on
whatever the shell's current directory happens to be — the exact class of
mistake that caused the 404.

Verification, all against the corrected server:

| Request | Result |
|---|---|
| `GET /` | 200 |
| `GET /index.html` | 200 |
| `GET /styles.css` | 200 |
| `GET /app.js` | 200 |
| `GET /manifest.json` | 200 |
| `GET /service-worker.js` | 200 |

## Phase 5 — Smoke test: what this runtime can and cannot verify

**Can verify here (and did, via the existing `tests/adversarial.js`
Playwright suite re-run against the corrected server — 23/23 pass):**

1. Initial screen renders — PASS
2. CSS loads (layout has no unintended horizontal overflow at 360px) — PASS
3. JavaScript initializes (flow navigation, state, summary all function) — PASS
6. Complete workflow can be traversed (Skip through all 7 steps to summary) — PASS
7. Back navigation behaves correctly (preserves prior field) — PASS
8. Run It Again works (self vs. friend comparison renders correctly) — PASS
9. Clear Session works (storage keys verified removed) — PASS
10. Refresh behavior matches documentation (mid-flow refresh resumes same step) — PASS
11. Manifest is accessible (200, valid JSON) — PASS
12. Service worker registers where supported (offline reload test passes) — PASS
13. No user-entered text is transmitted externally (full source re-scanned; only
    loopback `localhost` references anywhere, including in the new launcher
    script) — PASS
14. No invisible overlay intercepts touches (this is the specific dialog-backdrop
    bug fixed in the original build; automated click-through of the Clear
    Session dialog confirms it stays fixed) — PASS
15. No console-blocking JavaScript errors (Playwright run completed without
    uncaught page errors halting any scenario) — PASS

**Cannot verify from this runtime — genuinely require the user's physical
phone, not fabricated here:**

4. Buttons respond to *touch* specifically (as opposed to a simulated
   click event) — **NOT TESTED, requires physical touchscreen**
5. On-screen keyboard does not permanently obscure navigation — **NOT
   TESTED, requires a physical device's real IME, which this sandbox has
   no analog for**

These two remain open manual checks. They were open in the original
`RELEASE_REPORT.md` scope note as well; nothing in this recovery pass
closes them, because nothing in this environment changed the ability to
test them.

## Phase 6 — Launcher

Created `next-right-move/start-next-right-move.sh` (executable). It
resolves its own on-disk location (`$BASH_SOURCE`, symlink-safe) and uses
that as the project directory and server document root, so it cannot
repeat the "launched from the wrong folder" failure regardless of what
directory it's invoked from. Before starting, it checks whether the target
port already has a listener (via `fuser`/`lsof`) and, if so, prints the
owning PID and refuses to start a second server rather than silently
stacking one on top of another.

Tested:
- Invoked from an unrelated directory (`/`) with port 8080 already
  occupied by a prior server for this same app → correctly detected the
  conflict, printed the PID, exited without starting a duplicate.
- Same invocation after that PID was stopped → started cleanly, served
  all six checked paths at 200.

## Phase 7 — One-command Android open

`termux-open-url` is not present in this environment (confirmed via
`command -v`), so per the mission's own instruction ("if unavailable,
leave the normal launch workflow intact") no Termux:API package was
installed and no behavior was forced. The launcher does include a
best-effort branch that calls `termux-open-url` automatically *if it is
already present* on a real device, without making it a hard dependency —
harmless here, useful on an actual Termux install with Termux:API added.

## Phase 8 — Baseline freeze

Suggested tag: `NRM-v0.1-CLASSROOM`, applied locally to the commit that
includes this recovery (launcher script + this document). Not pushed to
any remote — per this mission's explicit instruction not to push without
separate authorization.

## Phase 9 — Evidence summary

```
Observed failure:
localhost:8080/index.html -> 404

Root cause:
Server document root was the repository root, one directory above the
project (next-right-move/); index.html was requested at a path that
doesn't exist at that root even though it exists one level down.
Reproduced exactly (byte-identical error body) to confirm.

Repair:
Serve with an explicit --directory flag pointing at the verified
canonical project path, and ship a self-locating launcher script so this
class of mistake can't recur regardless of invocation directory.

Physical Android validation:
PARTIAL — every check performable from this cloud sandbox passed (13 of
15 Phase-5 items, all server/app-logic/privacy checks). The 2 remaining
items (real touchscreen input, real on-screen-keyboard obscuring
behavior) require the user's actual phone and were not fabricated here.

Remaining blockers:
None functional or privacy-related. One standing scope item, unchanged
from the original RELEASE_REPORT.md: a manual pass on physical Android
hardware for touch/keyboard behavior specifically.
```

## Release status after this recovery

Unchanged from the prior release: **CLASSROOM_READY**, with the same
single scope caveat as before (now narrowed to exactly two physical-input
checks rather than "no device tested at all"). The 404 was a launch/ops
issue, not an application defect — no privacy or functional regression
was found, so no downgrade is warranted per this mission's own downgrade
condition ("if physical-device validation exposes a critical functional
or privacy defect"), which did not occur.
