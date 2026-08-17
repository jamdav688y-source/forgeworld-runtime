# Pocket Cortex — Phone Deployment

## Read this first

This document, and `scripts/forge_deploy.py` itself, were written and
tested from a cloud environment with no network path to any phone's
`127.0.0.1`. Every claim below about *this repository's code* (what it
checks, what it refuses, what it writes) was verified by running
`forge_deploy.py` against a disposable local git clone standing in for a
Termux checkout — same code path, same git operations, real backup and
restart and health-check behavior — but that is not the same as having
run it on an actual phone. Treat your first real run as the first real
test of that last mile. Start with `--dry-run`.

## The one-line Termux command

Run this from inside your existing `~/forgeworld-runtime` checkout on
the phone:

```bash
cd ~/forgeworld-runtime && git fetch origin && git checkout origin/claude/pocket-cortex-command-deck -- scripts/forge_deploy.py scripts/forge_reconcile.py && python3 scripts/forge_deploy.py --yes
```

What each part does:
1. `git fetch origin` — brings down the branch, changes nothing locally.
2. `git checkout origin/claude/pocket-cortex-command-deck -- scripts/forge_deploy.py scripts/forge_reconcile.py` —
   extracts *only* those two files onto disk (does **not** switch your
   branch or touch anything else), just enough to bootstrap the deploy
   tool itself.
3. `python3 scripts/forge_deploy.py --yes` — runs the actual staged,
   backed-up, divergence-checked deployment (defaults to
   `--root ~/forgeworld-runtime --ref origin/claude/pocket-cortex-command-deck --port 8080`).

If you'd rather see what it would do first, run the same command with
`--dry-run` appended in place of `--yes` — it performs every check and
writes nothing.

Requires: `git`, `python3`, and `node` (≥22.5) already installed in
Termux (`pkg install nodejs` if `node` isn't found — `forge_deploy.py`
will tell you if it's missing rather than failing unclearly).

## What `forge_deploy.py` actually does, in order

1. **identity** — fetches `origin`, confirms the target ref resolves.
2. **enumerate** — lists every file under `pocket-cortex/` plus
   `scripts/forge_reconcile.py` at that ref, then removes anything
   under `pocket-cortex/data/` or matching `*.db`/`*.sqlite*`/
   `research.db` from the list *in code*, not just by convention —
   there is no flag that puts those back in scope.
3. **reconcile_and_check** — runs `forge_reconcile.py` fresh (read-only)
   and refuses to continue if any file about to be deployed is
   classified `UNMERGED_LIVE`, `AUTHORITATIVE_LIVE`, or `UNKNOWN` — i.e.
   the live phone has something in that path this deploy can't explain.
   Prints exactly which file(s) and why, and stops. **Nothing is written
   at this point.**
4. **confirm** — requires `--yes` or an interactive `deploy` confirmation.
5. **backup** — copies every live file about to be touched into a
   timestamped directory *outside* `--root` (default:
   `~/forgeworld-backups/pocket-cortex-deploy-<timestamp>/`), before
   any write.
6. **deploy** — writes each file from the git ref via `git show
   <ref>:<path>`, staged through a temp file and renamed into place
   (atomic; a kill mid-deploy leaves old-or-new, never truncated).
7. **restart** — stops whatever is currently listening on the target
   port (`fuser`/`lsof`), starts `node pocket-cortex/server.js` detached
   so it outlives the deploy script.
8. **verify** — polls `http://127.0.0.1:8080/api/health` (bounded
   retries) and only reports success once it actually responds 200.

A `DEPLOY_REPORT.md` and a generated `rollback.sh` are written to the
backup directory every time, whether the deploy succeeds or fails.
Rollback restores exactly the files this deploy changed and explicitly
never touches `pocket-cortex/data/` — that directory is never written by
deploy in the first place, so there's nothing there to roll back.

## If it refuses to deploy

You'll see something like:

```
STAGE 3/8 [reconcile_and_check]: FAIL: 1 file(s) have unresolved live divergence
  pocket-cortex/lib/governance.js: UNMERGED_LIVE -- same path exists in [...] but content differs -- diverged
```

Look at that file on the phone. If overwriting it is actually correct
(e.g. it's an old local experiment you don't need), re-run with:

```bash
python3 scripts/forge_deploy.py --yes --force-acknowledge-divergence pocket-cortex/lib/governance.js
```

repeating the flag for each file you've reviewed and accepted. It is
still backed up before being overwritten.

## Rolling back

```bash
bash ~/forgeworld-backups/pocket-cortex-deploy-<timestamp>/rollback.sh
cd ~/forgeworld-runtime/pocket-cortex && ./start.sh
```

## Android smoke-test checklist

Run through this on the actual device after a deploy, in a mobile
browser pointed at `http://127.0.0.1:8080/` (or whatever `--port` you
used):

- [ ] Page loads; awakening screen animates in and clears within ~3s
      (or near-instantly if the OS/browser has reduced-motion enabled).
- [ ] Constellation renders correctly in portrait orientation at your
      phone's actual width (no clipped labels, no overlap).
- [ ] Typing in the goal field shows instant routing feedback
      (constellation nodes light up) before you submit.
- [ ] Submitting a goal (e.g. "Teach me something I do not understand.")
      opens the ACTIVE CORTEX workspace and shows a route
      (LEARN · EXPLAIN · ANALYZE).
- [ ] The on-screen keyboard does not permanently cover the goal input
      or the submit button when focused.
- [ ] NEXT RIGHT MOVE banner is visible and shows real text, not blank.
- [ ] EVIDENCE tab shows five indicator arcs with real (non-identical,
      non-round) values and readable basis text on tap/long-press.
- [ ] Tapping "YES" or "NO" in the evidence feedback updates the
      EVIDENCE indicator and appears in the evidence log below it.
- [ ] EXECUTE tab lists capabilities with independent CAPABILITY and
      AUTHORITY badges; `TRIGGER_PHONE_DEPLOY` shows
      `REQUIRES_APPROVAL` and has no working RUN button.
- [ ] HISTORY tab lists the mission you just created, and tapping it
      re-opens the same mission with the same route.
- [ ] Force-close the browser tab (or the app if installed as a PWA)
      and reopen `http://127.0.0.1:8080/` — the mission from HISTORY is
      still there (server-persisted, not lost on reload).
- [ ] Turn on airplane mode (or otherwise kill network to localhost —
      e.g. stop the `node server.js` process) and try submitting a new
      goal: the "POCKET CORTEX SERVER UNREACHABLE" banner appears,
      nothing silently pretends to succeed.
- [ ] Restore connectivity / restart the service: the banner clears on
      its own within ~30 seconds without a manual page reload.
- [ ] DEMONSTRATE button runs the scripted walkthrough; tapping anywhere
      interrupts it cleanly; confirm (via `adb logcat`, browser dev tools,
      or simply that HISTORY doesn't grow) that no mission was created by
      running it.
- [ ] Install to home screen (browser's "Add to Home Screen" /
      "Install app" prompt) and relaunch from the home screen icon —
      opens standalone, no browser chrome, correct icon.
- [ ] Rotate the phone to landscape and back — layout doesn't break or
      trap focus.

## Local vs. phone-shareable, one more time

Everything above serves `127.0.0.1` — reachable only from the same
phone. It does **not** make Pocket Cortex reachable from another device
on the same network, let alone the internet. That would require binding
`server.js` to `0.0.0.0` and exposing the port deliberately, which this
deployment does not do and which is a separate decision with its own
privacy/security review, not something to enable by default.
