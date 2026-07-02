# FORGEWORLD — Implementation Readiness Matrix

Mission 4 deliverable, part 3 of 4. Every determination below cites the specific
evidence it rests on — a verified file/line finding from Mission 2/3, a dependency edge
from `IMPLEMENTATION_DEPENDENCY_GRAPH.md`, or a live check run in this session. No
batch is marked READY on the basis of "looks fine" — per
`ARCHITECTURAL_DOCTRINE.md` §5.5, that is not a valid readiness state.

## 0. Environment Evidence Gathered This Session

Before assessing readiness, the following was verified directly (read-only checks, no
files modified):

```
$ echo $HOME
/root
$ test -d "$HOME/forgeworld"        → does not exist
$ test -f /data/data/com.termux/files/usr/bin/bash   → does not exist
$ which bash python python3 git tar jq
/usr/bin/bash /usr/local/bin/python /usr/local/bin/python3 /usr/bin/git /usr/bin/tar /usr/bin/jq
$ ls .github/workflows                → no .github directory at all
```

**Implication:** every interpreter dependency the repository's scripts need
(`bash`, `python`, `git`, `tar`, and `jq` for any future JSON-patch work) is present in
this environment. What's missing is (a) the `$HOME/forgeworld` path every script
hardcodes, and (b) any CI configuration to run checks automatically. This directly
confirms ISSUE-18 and ISSUE-20's findings with live evidence rather than inference, and
it means **ISSUE-18's fix is executable in this exact session** the moment it's
authorized — there is no missing tool blocking it.

---

## 1. Batch-Level Readiness Summary

| Batch | Status | Why |
|---|---|---|
| FIX_BATCH_01_CRITICAL | **PARTIALLY READY** | ISSUE-01, ISSUE-02 are READY (isolated, evidence-backed, no open dependencies). ISSUE-08 is BLOCKED — pending explicit user decision on remediation approach (freeze / redact / history-rewrite), per Mission 3 §4 and Architectural Doctrine §8 (destructive/human-facing decisions are never auto-resolved). |
| FIX_BATCH_02_STRUCTURAL | **PARTIALLY READY** | 9 of 10 items are READY once ISSUE-18 lands first (internal ordering, see Dependency Graph §3.3). ISSUE-07 is BLOCKED — its rename target depends on ISSUE-25 (Batch 5, unanswered). Batch cannot fully close without a Batch 5 decision landing first, a cross-batch dependency this matrix surfaces rather than hides. |
| FIX_BATCH_03_ARCHITECTURAL | **BLOCKED** | Every item in this batch either directly requires ISSUE-03/ISSUE-04 (single canonical state file, real state writer) or ISSUE-05 (event-ID scheme) — both Batch 2 items. Design/spec authoring for this batch could start in parallel; implementation cannot. |
| FIX_BATCH_04_DOCUMENTATION | **PARTIALLY READY** | `.gitignore`, the command-doc rewrite, and the relationships spec are READY today (no dependencies). `LICENSE` selection (ISSUE-21) and `linkedin_protocol.md` content (part of ISSUE-10) are BLOCKED on human decisions (legal terms; ISSUE-08's policy). |
| FIX_BATCH_05_LONG_TERM | **BLOCKED** | Depends on Batches 1–3 completing (Architectural Doctrine §4 hierarchy law) plus three explicit, currently-unmade human decisions: product identity (ISSUE-25), LLM API usage/cost approval (ISSUE-22), and confirmation that ISSUE-08's policy is both authored and actually enforced before any automated action touches real people (ISSUE-24). |

**No batch is fully READY.** This is the expected, correct state for a repository that
has never had any of its findings acted on yet — it is not a negative assessment of the
plan, it is the honest starting line.

---

## 2. Batch 1 — CRITICAL: Detailed Readiness

| Issue | Status | Evidence |
|---|---|---|
| ISSUE-01 | **READY** | Fix is fully specified (single-line change, Remediation Plan entry). No open prerequisite in the Dependency Graph. Environment check above confirms `python3` is available to test it in this session. |
| ISSUE-02 | **READY** | Fix is fully specified (brace-group the echo block). No open prerequisite. |
| ISSUE-08 | **BLOCKED** | Requires a decision this plan explicitly declines to make unilaterally (Remediation Plan §"Rollback strategy" for ISSUE-08: *"not something this remediation plan authorizes on its own"*). Evidence that this is still open: `doctrine/linkedin_protocol.md` remains 0 bytes as of this session (unchanged since Mission 2's discovery). |

**Batch verdict: PARTIALLY READY.** Recommend executing ISSUE-01 and ISSUE-02
independently of ISSUE-08's resolution — they have no relationship to each other
(confirmed in the Dependency Graph: no edge connects ISSUE-01/02 to ISSUE-08).

## 3. Batch 2 — STRUCTURAL: Detailed Readiness

| Issue | Status | Evidence |
|---|---|---|
| ISSUE-18 | **READY** | This session's environment check is the direct evidence: the fix (`FORGEWORLD_HOME` override + `env bash` shebang) is testable right now, in this sandbox, with tools already confirmed present. |
| ISSUE-20 Phase A | **READY, pending ISSUE-18 landing first** | Fully specified in the Remediation Plan; requires nothing not already available (evidence: §0 tool check). |
| ISSUE-03 | **READY** | Fully specified; no blocking dependency. |
| ISSUE-05 | **READY** | Fully specified; no blocking dependency. |
| ISSUE-06 | **READY** | Pure documentation diff against existing code; no dependency. |
| ISSUE-11 | **READY, benefits from ISSUE-20 Phase A landing first** for automated golden-output verification, but the refactor itself has no hard blocker. |
| ISSUE-14 | **READY** | Spec-authoring only; no dependency. |
| ISSUE-17 | **READY** | No dependency. |
| ISSUE-19 | **READY** | No dependency. |
| ISSUE-07 | **BLOCKED** | Dependency Graph §2 marks this as soft-gated on ISSUE-25 (Batch 5). Evidence it's still open: no `intelligence/PRODUCT_IDENTITY_DECISION.md` exists in the repository as of this session. |

**Batch verdict: PARTIALLY READY.** 9 of 10 items are executable now, with an internal
ordering (ISSUE-18 → ISSUE-20 Phase A → the rest) rather than a blocking one. ISSUE-07
is the batch's one true blocker and should either be deferred to run alongside Batch 5,
or the batch should be explicitly scoped as "Batch 2 minus ISSUE-07" if the user wants
to greenlight it before ISSUE-25 is answered.

## 4. Batch 3 — ARCHITECTURAL: Detailed Readiness

| Issue | Status | Evidence |
|---|---|---|
| ISSUE-04 | **BLOCKED** | Dependency Graph: requires ISSUE-03 (single canonical `world_state.json`) landed first — building a state writer against two disagreeing schemas would just encode the duplication permanently. |
| ISSUE-20 Phase B | **BLOCKED** | Requires ISSUE-04 (needs real state deltas to assert against) and ISSUE-20 Phase A (needs the harness to exist first). |
| ISSUE-13 | **BLOCKED (soft)** | Validation requires ISSUE-20 Phase B per the Dependency Ledger; the scoring logic itself could be drafted earlier but shouldn't be considered "done" without its validation path existing. |
| ISSUE-15 | **BLOCKED** | Requires ISSUE-05 (event-ID scheme) to reference which consequence a rollback entry targets. |
| ISSUE-09 | **PARTIALLY READY** | No hard blocker, but Architectural Doctrine §3 recommends co-landing with ISSUE-05 so the directory houses the correlation-key implementation rather than becoming a sixth empty-spec directory (repeating the exact pattern this batch exists to fix). |
| ISSUE-12 | **READY** | No dependency in the graph; can proceed independent of the rest of Batch 3. |
| ISSUE-16 | **READY** | No dependency in the graph; independent of the rest of Batch 3. |

**Batch verdict: BLOCKED**, with two items (ISSUE-12, ISSUE-16) that are individually
READY today but were grouped into this batch by risk tier, not by dependency — per
Dependency Graph §3, batch membership is a risk classification, not an execution
lockstep. They may be pulled forward without violating the hierarchy law, since neither
depends on Batch 2 output.

## 5. Batch 4 — DOCUMENTATION: Detailed Readiness

| Issue | Status | Evidence |
|---|---|---|
| ISSUE-10 (4 of 5 files) | **READY** | `doctrine/governance.md`, `doctrine/identity.md`, `tasks/roadmap.md`, `tasks/milestones.md` have no content dependency on anything else. |
| ISSUE-10 (`linkedin_protocol.md` specifically) | **BLOCKED** | Same evidence as ISSUE-08 — the file that would receive this content is the same file ISSUE-08's policy work must author; writing placeholder content first would violate Architectural Doctrine §1's "falsifiable closure" principle by creating the appearance of closure without substance. |
| ISSUE-21 (`.gitignore`) | **READY** | No dependency; purely mechanical. |
| ISSUE-21 (`LICENSE`) | **BLOCKED** | Explicit human decision, confirmed still open: no `LICENSE` file exists in the repository as of this session's directory listing. |

**Batch verdict: PARTIALLY READY.** The purely mechanical half of this batch (4 files
+ `.gitignore`) can proceed today; the two items gated on human decisions should be
tracked as open questions, not silently dropped.

## 6. Batch 5 — LONG_TERM: Detailed Readiness

| Issue | Status | Evidence |
|---|---|---|
| ISSUE-25 | **READY to decide (not to implement)** | This is a decision, not an engineering task — nothing technical blocks the user from making it today. It is listed BLOCKED for *implementation* purposes only because nothing downstream can proceed without the decision existing first. |
| ISSUE-22 | **BLOCKED** | Requires Batches 1–4 complete (hierarchy law) plus explicit user approval for external LLM API usage — no such approval has been requested or granted in this session; this plan does not assume it. |
| ISSUE-23 | **BLOCKED** | Requires ISSUE-25 answered; requires Batches 1–3 complete per the runtime evolution strategy in `ARCHITECTURAL_DOCTRINE.md` §9 (a Laptop node built against unreliable Phone-node state would just replicate the ISSUE-04 defect on a second node). |
| ISSUE-24 | **BLOCKED** | Requires ISSUE-08's policy landed and enforced (not just documented — Architectural Doctrine LAW 5 requires enforceability); requires ISSUE-25 to inform its design. Highest-risk item in the entire register to implement prematurely, because it is the first subsystem that would take real, automated action referencing real named individuals. |

**Batch verdict: BLOCKED.** This is correct and expected — Batch 5 was explicitly
designed to be the last thing to become ready (Remediation Plan §3: *"building on top
of an unreliable state layer and an unresolved privacy policy would just create new
instances of the same defect class this plan exists to close"*). Its one actionable
item today is ISSUE-25, and it is actionable by the user, not by engineering work.

---

## 7. Summary Table

| Batch | READY items | BLOCKED items | Human decision required? |
|---|---|---|---|
| Batch 1 | ISSUE-01, ISSUE-02 | ISSUE-08 | Yes — ISSUE-08 remediation approach |
| Batch 2 | 9 of 10 | ISSUE-07 | No (ISSUE-07 blocked on a Batch 5 decision, not a Batch 2 one) |
| Batch 3 | ISSUE-12, ISSUE-16 (dependency-independent, pullable early) | ISSUE-04, ISSUE-09 (soft), ISSUE-13, ISSUE-15, ISSUE-20 Phase B | No |
| Batch 4 | 4 files + `.gitignore` | `linkedin_protocol.md` content, `LICENSE` | Yes — LICENSE terms; and ISSUE-08 again |
| Batch 5 | ISSUE-25 (as a decision, not a build) | ISSUE-22, ISSUE-23, ISSUE-24 | Yes — product identity, LLM approval, PII policy enforcement |

**The single decision with the widest blast radius across this entire matrix is
ISSUE-25** (product identity) — it is the only open item that appears as a blocker in
three separate batches (2, 5, and indirectly 4 via ISSUE-08's framing of what the
network ledger is for). Recommend surfacing it to the user first, ahead of any
Batch 1 execution request, purely because of how many downstream items its answer
unblocks.
