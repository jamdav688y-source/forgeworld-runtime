# FORGEWORLD — Architectural Doctrine

Mission 4 deliverable, part 1 of 4. This is the constitutional interpretation layer for
all future engineering work on this repository. It is derived exclusively from
verified findings in `intelligence/REPOSITORY_INTELLIGENCE_MODEL.md` (Mission 2) and
`intelligence/CONSTITUTIONAL_REMEDIATION_PLAN.md` (Mission 3) — no new discovery was
performed to produce it. Where this document states a "law," it is because the same
pattern was independently observed at least twice across the prior missions, not
because it sounded right in isolation.

This document does not replace `governance/CONSTITUTION_v3.txt`. The Constitution is
the repository's **object-level** doctrine — what FORGEWORLD-the-simulation believes
about itself (event→evidence→memory→…→future-state). This document is the
**steward-level** doctrine — what governs how *engineering work on the repository
itself* should proceed so that the object-level doctrine eventually becomes true rather
than remaining aspirational prose. Keep the two separate: never edit
`governance/CONSTITUTION_v3.txt` to make this document's job easier, and never let this
document contradict it.

---

## 1. Core Architectural Philosophy

**Verified pattern:** across both prior missions, nearly every defect traced back to
one root behavior — *a specification was written before the code that implements it,
and nothing ever closed the loop.* `continuity/` (ISSUE-09), `linkedin_protocol.md`
(ISSUE-08/24), rollback semantics (ISSUE-15), reputation scoring (ISSUE-13), the
faction registry (ISSUE-12), the Council of Minds' answers (ISSUE-22) — each is a spec
that predates, and still lacks, its implementation.

This is not automatically a flaw. Spec-first is a legitimate and often superior
development order. It became a flaw here only because **nothing ever verified that the
gap was closed** — there is no lint, test, or process step in the repository that
distinguishes "documented and built" from "documented and imagined." The philosophy
this doctrine adopts is not "stop writing specs first" — it is:

> **Every spec must carry its own falsifiable closure test.** A capability is not
> "done" because a `.txt` file describes it; it is done when a check exists that fails
> while the capability is missing and passes once it exists (`intelligence/
> IMPLEMENTATION_READINESS_MATRIX.md` operationalizes this per batch).

## 2. Stable Design Principles

These principles were extracted because they appear **consistently and without
contradiction** across `CONSTITUTION_v1.txt`, `CONSTITUTION_v3.txt`,
`EVOLUTION_DIRECTIVE_v1.txt`, `PHASE_5_RUNTIME.txt`, and
`master_persistence_directive.txt` — five independently-authored governance documents
that never disagree with each other on these points, which is itself evidence they are
the repository's true invariants rather than one author's passing preference.

1. **The causal chain is the one true invariant.**
   `EVENT → EVIDENCE → MEMORY → REPUTATION → RELATIONSHIP → FACTION → GOVERNANCE →
   CONSEQUENCE → WORLD_STATE → FUTURE_STATE` appears, in the same order, in every
   governance document that defines a chain at all. Any new subsystem must declare
   which link of this chain it occupies before it is built. A subsystem that can't be
   placed on this chain doesn't belong in the pipeline (it may still belong in Ops or
   Docs — see §4).
2. **Resource Conservation Mandate is non-negotiable, not aspirational.**
   No redundant processes, no duplicate records, no perpetual execution, no
   expansion without increased explanatory power, dormancy when idle. Mission 3 found
   this principle violated by ISSUE-03 (duplicate state files), ISSUE-05 (duplicate
   memory-writers with no shared key), ISSUE-07 (duplicate NPC directories), and
   ISSUE-11 (triplicated diagnostic scripts) — four independent violations of the same
   one rule. Treat any new duplication as a Batch-1-severity finding by default, not a
   style nit.
3. **Persistence and deletion both require review.** Stated explicitly in
   `CONSTITUTION_v1.txt`'s Forbidden list and directly violated by ISSUE-16
   (installers overwrite without review) and ISSUE-08 (real personal data persisted
   without a governance review ever having happened). Any future script that writes or
   deletes a file that isn't purely a machine-generated log line must have an explicit
   review or confirmation gate.
4. **Authority and reputation must be traceable to evidence, never asserted
   directly.** Violated today by ISSUE-12 (factions referenced with no registry) and
   ISSUE-13 (reputation "evaluated" without ever producing a value). A future
   subsystem may not claim a reputation, authority, or consequence exists unless it can
   point to the specific evidence record that produced it.
5. **The system remains dormant unless invoked.** `PHASE_5_RUNTIME.txt`'s Resource
   Law ("Do not run loops. Do not poll continuously. Act only when manually invoked.")
   has never been violated in this repository — it is the one design principle with a
   perfect track record. Any future automation (Council-of-Minds LLM calls, a
   LinkedIn loop) must preserve this: manually triggered, not scheduled/polling, unless
   a future mission explicitly revisits this law with the user's sign-off.

## 3. Repository Laws

Laws are stricter than principles: violating one should block a change from landing,
not just get noted for later.

- **LAW 1 — No new state file without a single canonical location.** (Closes the
  ISSUE-03 defect class permanently.) Before creating any new `*_state.json` or
  equivalent, `grep -r` the repository to confirm no file with overlapping semantics
  already exists.
- **LAW 2 — No new evidence-writing script without the shared event-ID scheme.**
  (Closes the ISSUE-05 defect class.) Once `COMPOUND-01` (see
  `COMPOUNDING_ARCHITECTURE_REPORT.md`) lands, every script that appends to
  `events.log`, `memory.log`, `consequences.log`, `council.log`, etc. for a given event
  must use the same correlation ID for that event, full stop.
- **LAW 3 — No script ships without a regression check that fails on its known-broken
  behavior.** (Closes the ISSUE-01/ISSUE-02 defect class — both bugs shipped and went
  undetected specifically because nothing asserted expected output.) A fix isn't
  "landed" until `diagnostics/regression_check.sh` (or its successor) has a case that
  would have caught it.
- **LAW 4 — No installer overwrites a file without a review/diff step once that file
  has ever been hand-edited.** (Closes ISSUE-16.)
- **LAW 5 — No real third-party personal data may be added to any file in this
  repository without the governance policy in `doctrine/linkedin_protocol.md` existing
  and being followed.** (Closes ISSUE-08 permanently, not just for the three existing
  entries.) This law is currently **unenforceable by tooling** because the policy file
  is empty — until Batch 1/4 lands, treat this as a manual, human-checked gate.
- **LAW 6 — Documentation describing a command surface must be generated from, or
  mechanically checked against, the code that implements it.** (Closes the ISSUE-06
  defect class permanently, not just this one instance.)
- **LAW 7 — No subsystem is "complete" without an entry in the subsystem catalog**
  (§9 of `REPOSITORY_INTELLIGENCE_MODEL.md`) **covering all nine required attributes.**
  This keeps the architectural memory current as the system grows, per the Knowledge
  Preservation Rules in §6 below.

## 4. Implementation Hierarchy

Verified in `CONSTITUTIONAL_REMEDIATION_PLAN.md` §3 and restated here as a durable
rule, not a one-time sequencing choice:

```
CRITICAL  (stop active harm; zero/near-zero blast radius)
   │
   ▼
STRUCTURAL  (remove ambiguity: dedupe, name things once, stand up the test harness)
   │
   ▼
ARCHITECTURAL  (the only tier allowed to change core pipeline *behavior*)
   │
   ▼
LONG_TERM  (net-new capability; gated on the above, plus explicit product/consent decisions)

DOCUMENTATION runs in parallel with all four tiers; it never blocks or is blocked by
code, except where a doc requires a human decision (LICENSE terms, privacy policy
content) rather than just a description of existing behavior.
```

**Law:** no change may be classified ARCHITECTURAL or LONG_TERM if a CRITICAL or
STRUCTURAL prerequisite for it is still open. (See
`IMPLEMENTATION_DEPENDENCY_GRAPH.md` for the issue-level enforcement of this.)

## 5. Validation Philosophy

**Verified pattern:** every defect found in Mission 2/3 was invisible to the
repository's own tooling. `diagnostics/*.sh` reports state, it never asserts state is
*correct*. This is the single largest systemic gap identified (ISSUE-20), and it is
the reason this doctrine treats validation as a first-class architectural concern
rather than a testing afterthought.

Rules:
1. **Assertions over narration.** A diagnostic script that prints "recent events:
   `<tail>`" has produced a report, not a validation. A diagnostic script only
   validates something if it can exit non-zero.
2. **Synthetic-event testing is the primary validation unit.** Because the entire
   pipeline is event-driven, the correct test primitive is "push one synthetic event
   through the pipeline, assert on every downstream artifact it should have touched."
   This single pattern validates Event Logger, Memory Writer, Reputation, Relationship,
   Faction, Council, Consequence, and World State subsystems simultaneously — one test
   shape, reused everywhere, rather than one bespoke test design per subsystem.
3. **Golden-output comparison for anything that only reformats existing data**
   (diagnostics scripts, `forge-world`'s renderer) — no new assertions need to be
   invented, just a recorded-good baseline byte-diffed against current output.
4. **Validation infrastructure must run outside Termux.** (Direct consequence of
   ISSUE-18.) Verified in this session: this sandbox has `/usr/bin/bash`, `python3`,
   `git`, `tar`, and `jq` available, but no `/data/data/com.termux/...` path and no
   `$HOME/forgeworld` directory. Any regression suite must accept a
   `FORGEWORLD_HOME` override (or equivalent) to be runnable anywhere a future Claude
   Code session, CI runner, or laptop node needs to verify it.
5. **A batch is not "ready" on the basis of code review alone.** See
   `IMPLEMENTATION_READINESS_MATRIX.md` — readiness requires either an existing passing
   check or an explicit, named human decision still pending. "Looks correct" is not a
   readiness state.

## 6. Knowledge Preservation Rules

1. **The `intelligence/` directory is permanent architectural memory, not a scratch
   log.** Never regenerate `REPOSITORY_INTELLIGENCE_MODEL.md` or
   `CONSTITUTIONAL_REMEDIATION_PLAN.md` from scratch in a future session — extend them.
   If a future mission discovers a new subsystem, add a new §9.x entry; if it finds a
   new defect, add a new ISSUE-NN; do not re-walk the whole tree and rewrite the
   document.
2. **Every fix must update the artifact that documented the problem it fixes.**
   When ISSUE-01 is actually implemented, `CONSTITUTIONAL_REMEDIATION_PLAN.md`'s entry
   for ISSUE-01 should be annotated resolved (not deleted — the root-cause analysis
   remains valuable history), and `REPOSITORY_INTELLIGENCE_MODEL.md` §9.10's failure
   mode note should be updated to reflect the fix.
3. **Numbering is permanent.** ISSUE-01 always means the `forge-world` Python
   invocation bug, even after it's fixed and even if renumbering would look tidier.
   Stable IDs let future documents (like this one) cite prior findings unambiguously.
4. **New documents extend the doctrine tree; they don't fork it.** Any future
   `intelligence/*.md` file should state, in its opening section, which prior documents
   it builds on and confirm it isn't re-deriving something already established — this
   document and its three siblings each do so explicitly.

## 7. Evidence Requirements

Carried forward unchanged from `CONSTITUTIONAL_REMEDIATION_PLAN.md`'s per-issue
template, generalized into a standing rule: **no claim about the repository's
behavior is valid in an architectural document unless it cites a specific file, line,
or command output.** This document itself follows that rule — every principle in §2 and
every law in §3 cites the specific ISSUE-NN that justifies it. A future steward
document that says "the pipeline is unreliable" without naming which script and which
verified failure mode is not doing steward work; it's speculation, and it is exactly
the class of untraceable claim §2 Principle 4 rules out for the object-level system —
this doctrine holds itself to the same standard it imposes on FORGEWORLD.

## 8. Rollback Philosophy

Verified pattern: the repository's persistence model is append-only logs. This is a
legitimate, auditable design (it already gives free history/undo at the *file* level
via git) but it currently has no story for undoing a *logical* action once logged
(ISSUE-15).

Rule: **prefer compensating entries over mutation, always.** When ISSUE-15 lands, a
rollback is a new log line that references the original event's correlation ID and
declares it superseded — never an edit or deletion of the original line. This preserves
the audit trail the Constitution requires ("Can it be replayed? Can it be audited?")
while still giving the system a working notion of reversal. Any future subsystem that
needs "undo" semantics should default to this pattern rather than inventing a new one;
a second, different rollback mechanism appearing anywhere in the repo would itself be a
Resource Conservation Mandate violation (see LAW 1's sibling principle applied to
mechanisms, not just files).

File-level rollback (installers, this doctrine's own documents) uses git revert — no
new mechanism needed there; §3 of `CONSTITUTIONAL_REMEDIATION_PLAN.md`'s "Rollback
strategy" field already defaults to this for every code-level issue, correctly.

Destructive, hard-to-reverse operations (git history rewrite to remove committed PII,
LICENSE selection, any decision that touches real third parties) are **never**
automated under this doctrine — they require the explicit human sign-off already
flagged in `CONSTITUTIONAL_REMEDIATION_PLAN.md` §4 and reaffirmed here as a permanent
rule, not a one-time caveat.

## 9. Runtime Evolution Strategy

The repository currently has one node (Phone/Termux) fully specified and zero nodes
(Laptop) implemented, despite a two-node topology being named in every doctrine file.
Runtime evolution should proceed in this order, and no other:

1. **Make the one node that exists correct and portable** (Batches 1–2: fix the
   active bugs, remove duplication, add the `FORGEWORLD_HOME` portability shim). A
   second node built on top of an unreliable first node just doubles the defect
   surface.
2. **Make the one node's state trustworthy** (Batch 3: close the dead-state pattern,
   ISSUE-04). Nothing about a Laptop node makes sense to design against a
   `world_state.json` that the Phone node itself doesn't reliably write.
3. **Only then design the Laptop node** (ISSUE-23, Batch 5) — and design it to consume
   the now-trustworthy state file/event stream, not to duplicate the Phone node's
   logic. If the Laptop node ever needs its own "world state," that is itself a LAW 1
   violation waiting to happen; it must read the one canonical state, not maintain a
   second copy.
4. **AI integration (Council of Minds, ISSUE-22) is a Phone-or-Laptop-agnostic
   service**, not tied to either node specifically — design it to be callable from
   wherever `resolve_event.sh`'s successor runs, using the event-ID scheme (§3 LAW 2)
   as its input contract.

## 10. Commercial Evolution Strategy

Verified from Mission 2 §6 (Commercial Asset Graph) and Mission 3's Batch 5 framing:
the repository currently contains **one** asset with confirmed, portable commercial
value independent of any product decision — the event-sourced governed-continuity
vocabulary itself (the causal chain + Resource Conservation Mandate). Everything else
(RPG skin, LinkedIn loop, personal-CRM framing) is a *use* of that vocabulary, not a
separate asset, and each use implies a different data model and privacy posture.

Strategy:
1. **Do not invest further build effort in product-specific features (ISSUE-23,
   ISSUE-24) until ISSUE-25 (product identity) is explicitly answered.** This was
   already stated in Mission 3; this doctrine elevates it from a batch note to a
   standing commercial rule, because every subsystem touched by Batch 5 has this same
   dependency.
2. **Treat the doctrine/governance vocabulary as the exportable asset regardless of
   which product identity wins.** If FORGEWORLD ships as an RPG engine, a personal
   CRM, or a general agent-memory framework, the causal chain and conservation mandate
   travel with it unchanged — future work that strengthens that vocabulary (better
   event-ID scheme, real reputation scoring, real rollback) pays off under all three
   futures simultaneously, which is exactly why Batches 1–3 were sequenced ahead of the
   identity decision in the first place.
3. **Real personal data (ISSUE-08) is a commercial liability until it is governed, not
   an asset.** No commercial narrative built on `npcs/network.md` should proceed before
   LAW 5 is enforceable.
