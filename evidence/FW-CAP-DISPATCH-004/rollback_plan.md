# Rollback Plan — FW-CAP-DISPATCH-004

## What actually changed on disk

Nothing outside this mission's own new/modified files was touched. No
third-party software was installed, cloned, or executed at any point (see
`capability_dispatch/THIRD_PARTY_SAFETY_BOUNDARY.md`). Every "installation"
and "authority" state this run produced lives in ephemeral, gitignored
runtime files (`capability_dispatch/data/`, `router/decisions.jsonl` and
`capabilities/history.jsonl` entries written during isolated test runs
only — the tracked copies of those two files were verified clean before
and after every test run in this session).

## Rollback is a pure git operation

Because nothing was installed and no shared/tracked state was mutated by
a real (non-isolated) run, rolling back this mission is exactly:

```bash
git checkout main
git branch -D feature/fw-cap-dispatch-004   # local branch only
# if pushed: git push origin --delete feature/fw-cap-dispatch-004
```

No data migration, no service restart, no credential revocation, and no
third-party cleanup is required, because none of those things happened.

## Update (2026-08-20 revision): the real artifact has now been ingested

The authoritative `FW-CAP-DISPATCH-004.json`/`.md` were committed by the
repository owner (`611b41ef8`) under `capability_dispatch/intake/` and are
**tracked, source-of-truth files** — never gitignored, never
content-addressed alongside derived/runtime data. Rolling back *only*
this ingestion (keeping the rest of the mission) is:

```bash
git rm capability_dispatch/intake/FW-CAP-DISPATCH-004.json capability_dispatch/intake/FW-CAP-DISPATCH-004.md
git rm capability_dispatch/src/authoritative_intake.py capability_dispatch/tests/test_authoritative_intake.py
# then revert the evidence/FW-CAP-DISPATCH-004/*.json files' authoritative_* sections back to their pre-revision content (git log -- evidence/FW-CAP-DISPATCH-004/ shows the exact prior commit)
```

`ingest_authoritative_packet()` running against them produced no side
effects on any tracked file other than what this revision's own commit
contains — see `authoritative_dispatch_output.json` for the full raw
object graph, and the section below for what *any* real ingestion
(this one included) writes to gitignored/tracked runtime files.

A future session running `ingest.ingest_candidate_packet()` (the
TEST_FIXTURE-only synthetic parser) or `authoritative_intake.ingest_authoritative_packet()`
(the real-shape parser, now exercised for real) against a NEW artifact
will write:

- a governed copy under `capability_dispatch/data/artifacts/<sha256>.json` (gitignored)
- Execution Ledger entries into `whatsapp/ledgers/execution_ledger.jsonl` (gitignored)
- `DispatchDecision` entries into `router/decisions.jsonl` (**tracked** — same file `mission_router.route()` already writes to)
- `DispatchLearningRecord`-derived entries into `capabilities/history.jsonl` (**tracked** — same file `record_outcome.record()` already writes to)

To roll back a real run's effect on the two tracked files:

```bash
git diff router/decisions.jsonl capabilities/history.jsonl   # review exactly what was appended
git checkout -- router/decisions.jsonl capabilities/history.jsonl   # discard, if desired
```

Both files are strictly append-only by convention (never rewritten in
place by any function in this codebase — see `TestDispatch012RoutingLearning`'s
append-only assertions), so `git checkout --` cleanly reverts to the
pre-run state with no partial-write risk.

## Authority policy fixtures added

Two additive policy fixtures were added to `governance/policy_defaults.json`:
`POLICY-sandbox-probe-candidate-v1` (capability `SANDBOX_PROBE_CANDIDATE`)
and `POLICY-install-third-party-capability-v1` (capability
`INSTALL_THIRD_PARTY_CAPABILITY`). Removing them (reverting that one file)
fully reverts `governance.authority.evaluate_authority()`'s behavior for
those two capability strings back to `UNKNOWN` (no matching policy) — no
other policy in that file is modified, so no other capability's authority
behavior is affected by a rollback.

## Verification a rollback succeeded

```bash
python3 -m pytest tests/governance whatsapp/tests perception/tests -q   # unaffected suites still pass
git status --short   # clean
```
