# External Validation Brief — ForgeWorld WhatsApp Membrane

A compact, non-promotional summary for a reviewer with no prior context on this project. Written to be
checked, not believed.

## Original claim

Build a governed WhatsApp intake-to-response pipeline (webhook → authenticate → normalize → classify →
draft → human-approve → send → reconcile) for a personal project ("ForgeWorld") exploring a future
business use case, with strict human-in-the-loop control and no autonomous customer-facing action.

## Implementation attempted

A self-contained Python module (`whatsapp/`, stdlib-only, no third-party dependencies) implementing every
stage of that pipeline against the real, currently-documented Meta WhatsApp Cloud API contract
(signature verification, 24h customer-service-window rule, template requirements — verified against live
Meta developer docs, not assumed). Outbound sending defaults to disabled
(`OUTBOUND=DRAFT_ONLY`) and fails closed without credentials, which do not exist for this project.

## Failures discovered (and when)

Two review passes surfaced 7 real defects, none present in the original "43/43 passing" claim's own
awareness at the time it was made:

1. No binding between an approved draft and the phone number it was actually sent to (recipient
   confusion risk).
2. No idempotency guard on sending — a retry could double-message a customer.
3. No file locking on the append-only ledgers — concurrent writers could corrupt a line, and a single
   corrupted line crashed every reader.
4. A hardcoded fallback pseudonymization salt that silently ran if the real one was never configured.
5. Raw exception content (occasionally including malformed input) leaking into the durable evidence
   ledger.
6. **A CI "offline sanity check" that was itself broken** — its own network-blocking approach broke
   Python's `ssl` module import, causing 3 of 9 test files to fail to import for a reason unrelated to
   any real network call. This was only caught when the check was actually *executed* for the first time
   during a later verification pass — it had been written, described as working, and committed without
   ever being run standalone.
7. A hardcoded personal email address used as a throwaway test value.

Full details, reproducers, and patches: `whatsapp_failure_correction_ledger.md`.

## Corrections made

All 7 defects have a committed code change and either a passing regression test or an explicitly
disclosed inspection-only verification (2 of the 7 — see the ledger for which). No credential was added
and no live network call was made at any point during discovery or correction.

## Adversarial tests added

17 new tests (`whatsapp/tests/test_adversarial.py`), on top of the original 43: 8-thread concurrent
ledger writes, concurrent webhook deliveries, webhook replay, send-replay/idempotency, 4 ledger-corruption
scenarios, duplicate/late/invalid approval-state transitions, forged delivery-status webhooks, recipient
mismatch, missing-salt configuration, and emergency-stop enforcement mid-conversation across multiple
pending drafts simultaneously.

## Measurable outcome

- 60/60 tests passing, 3 consecutive clean runs (deterministic, no flakiness observed), exit code 0 each
  time. Raw log: `whatsapp/reports/test_run_evidence.txt`.
- 0 network calls in any test (verified by a corrected socket-level guard — see defect 6 above).
- 0 hardcoded secrets found in a full-history git scan (`git log --all -p`), repo-wide, not just this PR.
- 13 material claims, each with a named implementation artifact, named test(s), an observed result, and
  an explicitly stated residual risk: `whatsapp_claim_evidence_matrix.json`.

## What this evidence supports

- The pipeline mechanics (signature verification, dedup, classification-as-data not instruction, human
  approval gating, fail-closed outbound, emergency stop) work correctly under the adversarial conditions
  tested, in this single-process/single-machine test environment.
- The team/process that produced this is willing to find and disclose its own defects, including a defect
  in its own verification tooling (defect 6), rather than only report passing numbers.
- The code has no external repository-location assumptions baked in except one identified, disclosed
  exception (`draft.py` reads a sibling repo's `memory/memory.log`; degrades gracefully but silently if
  absent — see `whatsapp_migration_dry_run.md` §3).

## What this evidence does NOT prove

- **It does not prove correctness against real Meta WhatsApp traffic.** No live webhook has ever reached
  this code. All 60 tests run against hand-written, sanitized fixtures.
- **It does not prove the CI workflow works inside real GitHub Actions** — only that the exact commands it
  runs were separately verified to work locally. The workflow itself has not yet executed on GitHub's
  infrastructure (see claim C-10's residual risk).
- **It does not prove this repository is the right place for this code to live long-term.** A separate,
  evidence-based review concluded the opposite: this repository's own doctrine describes itself as a
  personal RPG/productivity system, not a business system of record (`pre_merge_certification.md` §1).
  No canonical business repository has been identified or created; this brief takes no position on where
  one should be, since that is an operator decision, not a technical finding.
- **It does not prove the flock-based concurrency protection holds across processes on all filesystems**
  — tested with Python threads on local disk; not tested across OS processes or a network filesystem.
- **It does not prove the approval/authority guards are unbypassable** — they protect the intended API
  surface (`approval.py`, `outbound.py`); a caller with direct access to append to the ledger file could
  still write a conflicting record. This is disclosed, not hidden, in the claim-evidence matrix (C-05/C-13).

## Remaining boundary / next test

The single most valuable next test is **not** more adversarial unit testing of this code in isolation —
diminishing returns are visible. It is: (1) confirm the corrected CI workflow actually runs green on a
real GitHub Actions execution (currently unverified), and (2) resolve the repository-boundary question,
since no amount of additional code-level testing changes the finding that this repo has not been
established as the system's canonical home.
