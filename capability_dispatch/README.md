# FORGEWORLD Dynamic Capability Dispatch (FW-CAP-DISPATCH-004)

Turns an external observation of candidate tools/capabilities into, at
most, a *proposal* — never an installation. See
`THIRD_PARTY_SAFETY_BOUNDARY.md` for the structural guarantee that nothing
in this package installs, clones, or executes anything.

## Why a capability list is an observation source, not an installation queue

A list of tools someone noticed (in a screenshot, a README, a chat) tells
you those tools *exist and were observed* — nothing about whether they are
what they claim to be, safe, licensed compatibly, actively maintained, or
already redundant with something this runtime already has. Star counts and
social engagement are popularity signals, not identity, safety, license,
quality, or usefulness signals — `CapabilityCandidate` (see `src/schema.py`)
has no field for popularity at all, so nothing downstream can even read
one. Every candidate starts at a fixed epistemic floor:

```
IDENTITY: UNVERIFIED       SAFETY: NOT_ASSESSED
LICENSE: NOT_ASSESSED      MAINTAINABILITY: NOT_ASSESSED
INSTALLATION: NOT_INSTALLED  AUTHORITY: NOT_GRANTED
PROMOTION: NOT_ELIGIBLE
```

No function in this package can construct a candidate at any stronger
state (`schema.freshly_ingested_candidate_is_at_epistemic_floor()` is
checked at ingest time), and strengthening only ever happens through an
explicit, separately-evidenced step — never by mutating a candidate
directly.

## The problem-first dispatch sequence

```
PROBLEM -> ROOT-CAUSE HYPOTHESIS -> DESIRED OUTCOME -> SUCCESS METRIC
  -> CAPABILITY REQUIREMENT -> CANDIDATE RETRIEVAL -> IDENTITY RESOLUTION
  -> OVERLAP ANALYSIS -> AUTHORITY + SECURITY + LICENSE GATES
  -> SMALLEST SUFFICIENT TOOLSET -> SANDBOX PROBE -> EXECUTION -> EVIDENCE
  -> ROUTING-POLICY IMPROVEMENT
```

`gate.check_problem_first_gate()` enforces the first four steps: a mission
missing `problem_statement`, `desired_outcome`, or `success_metric` halts
immediately with a structured hard-block (`MISSING_PROBLEM_STATEMENT` /
`MISSING_DESIRED_OUTCOME` / `MISSING_SUCCESS_METRIC`) rather than guessing.
`dispatch.run_dispatch()` sequences everything after that.

## Module map

| Stage | Module |
|---|---|
| SOURCE OBSERVATION ingest | `src/ingest.py` |
| CANDIDATE IDENTITY RESOLUTION | `src/identity.py` |
| REGISTRY OVERLAP ANALYSIS | `src/overlap.py` |
| PROBLEM-FIRST GATE | `src/gate.py` |
| DYNAMIC DISPATCH ENGINE | `src/dispatch.py` |
| CONTEXT COMPILATION | `src/context.py` |
| DISPATCH LEARNING RECORD | `src/learning.py` |
| THIRD-PARTY SAFETY BOUNDARY | `src/safety_boundary.py` |
| objects (all 8 logical records) | `src/schema.py` |

## Identity resolution

`identity.py`'s `IdentityResolver` interface can resolve a candidate to
`VERIFIED`, `AMBIGUOUS`, `UNAVAILABLE`, or `REJECTED`. Two implementations
exist: `FixtureIdentityResolver` (deterministic offline mock — the only
one this proof exercises) and `UnwiredRegistryIdentityResolver`
(documented extension point for a real, read-only metadata lookup;
raises `NotImplementedError` today). A structural override in
`resolve_identity()` forces any candidate whose `canonical_hint` is a
known link-shortener domain (`bit.ly`, `tinyurl.com`, ...) to `AMBIGUOUS`
regardless of what a resolver claims — shortened links are never resolved
by inference, per the mission's explicit constraint. No resolver ever
installs, clones, or executes anything to determine identity.

## Overlap classifications

`overlap.py` compares a **VERIFIED** candidate's inferred function tags
(via a small, hand-maintained `CATEGORY_FUNCTION_TAGS` table — the same
posture as `whatsapp/src/classify.py`'s keyword lists, not a claim of
semantic understanding) against `capabilities/registry.json`'s existing
entries:

- `UNIQUE_GAP` — no existing capability shares any inferred function tag
- `PARTIAL_OVERLAP` — some but not all tags shared
- `FUNCTIONAL_DUPLICATE` — an existing capability already covers ≥75% of the candidate's tags
- `ARCHITECTURAL_CONFLICT` — reserved for a matched capability whose trust posture fundamentally conflicts (no case in this proof's fixtures triggers it — see `overlap_analysis_report.json`)
- `UNRESOLVED` — identity is not yet `VERIFIED`; overlap is never even attempted before identity resolution completes

## Dispositions

`dispatch._classify_disposition()` is an ordered, auditable decision
tree — exactly one branch fires per candidate:

| Disposition | Meaning |
|---|---|
| `REUSE` | an already-registered capability already satisfies the requirement; no candidate needed |
| `ADAPT` | partial overlap with something existing; could be extended |
| `SANDBOX_PROBE` | verified, unique-gap, authorized, reversible — eligible for an isolated test run |
| `OBSERVE` | unique-gap, authorized, but verification (safety/license/maintainability) is incomplete |
| `DUPLICATE` | functionally redundant with something already registered |
| `REJECT` / `BLOCK` | a hard-block condition fired (identity ambiguous, unbounded execution surface, license incompatible, security review failed, architectural conflict, no authority, or insufficient evidence) |

## Smallest sufficient set, not the largest toolset

`dispatch.select_smallest_sufficient_set()` covers each required
capability class using, in order of preference: (1) an already-registered
capability that already satisfies it outright (`REUSE`, no candidate
involved at all), then (2) the best-scoring eligible candidate
(`REUSE`/`ADAPT`/`SANDBOX_PROBE` only — `OBSERVE`/`DUPLICATE`/`REJECT`/`BLOCK`
are never selected for execution). Component scores
(`dispatch.score_candidate()`) are preserved per-axis — identity
confidence, safety/license/maintainability, registry-overlap fit,
reversibility, cost, latency, and (when a candidate matched an existing
capability) that capability's own historical performance via
`router.mission_router`'s existing scoring — never collapsed into one
opaque number.

## Authority and execution-surface gates

`governance.authority.evaluate_authority()` is called directly (not
reimplemented) against two new, additive policy fixtures in
`governance/policy_defaults.json`:

- `SANDBOX_PROBE_CANDIDATE` (`ALLOWED_BOUNDED`, local-only) — what a
  candidate needs before `SANDBOX_PROBE` can even be considered
- `INSTALL_THIRD_PARTY_CAPABILITY` (`HUMAN_ONLY`) — forward-looking; no
  code path in this mission ever checks it, since no installation
  authority is exercised here

`schema.is_unbounded_execution_surface()` independently blocks any
candidate whose `DispatchProfile` requires shell + credentials + network
with no declared reversibility — regardless of authority state.

## Sandbox-probe requirements

A candidate reaches `SANDBOX_PROBE` only when **all** of: identity
`VERIFIED`, overlap `UNIQUE_GAP`, `SANDBOX_PROBE_CANDIDATE` authority
granted, all three `VerificationResult` dimensions (`safety`, `license`,
`maintainability`) `PASSED`, and a `DispatchProfile` declaring
`reversibility="reversible"`. This mission computes and records that
disposition but never authorizes or performs an actual execution — see
`THIRD_PARTY_SAFETY_BOUNDARY.md`.

## Learning-record semantics

`learning.record_dispatch_learning()` computes a deterministic
`success_score` (an agreement function between predicted and observed
utility/cost/latency, capped low by any failure classification or failed
rollback) and writes it through `router.record_outcome.record()` — the
same 4-field write path (`capability_id`, `mission_class`, `success_score`,
`notes`) every other routing decision in this repository already uses.
The richer detail (predicted/observed pairs, failure classification,
rollback result, evidence sufficiency) rides inside `notes` as a JSON
string, so `router.mission_router.py`'s existing `historical_stats()`
reader is unaffected and unmodified.

## How routing evidence evolves

Every write to `capabilities/history.jsonl` is append-only —
`record_outcome.record()` never rewrites a prior line (see
`TestDispatch012RoutingLearning` for a direct assertion of this).
`router.mission_router.route()`'s `historical_stats()` reads that same
growing file back on every future routing decision — so a
`DispatchLearningRecord` written today changes tomorrow's `score_candidate()`
output for the same capability/mission-class pair, automatically, with no
separate "apply learning" step. A learning record never itself grants
authority or changes a `promotion_status` — those remain separate,
explicit decisions (`test_learning_never_grants_authority_or_promotion`).

## How to add a future candidate observation

1. Produce a JSON packet shaped like `fixtures/FW-CAP-DISPATCH-004.synthetic.json`
   (`artifact_id` containing `"FW-CAP-DISPATCH-004"`, `candidate_count`,
   `candidates: [{observed_name, observed_category, canonical_hint, maintainer_hint, source_notes}]`).
2. `ingest.ingest_candidate_packet(path, capture_source=...)` — governed,
   content-addressed, fails closed on any of the 10 validation steps.
3. Resolve identity for each candidate (`identity.resolve_identity` with
   a real, wired `IdentityResolver` once one exists — `FixtureIdentityResolver`
   for offline testing).
4. `overlap.analyze_overlap()` per candidate.
5. Build a `DispatchProfile` and run safety/license/maintainability
   `VerificationResult`s for anything that might reach `SANDBOX_PROBE`.
6. `dispatch.run_dispatch(mission_request, run_id, source_observation, candidate_bundles, decided_by)`.

## How to reproduce the tests

```bash
python3 -m pytest capability_dispatch/tests/test_dispatch_matrix.py -v
```

No live network access is required or attempted —
`capability_dispatch/tests/base.py` monkeypatches every path this package
writes to into a temp directory and replaces `socket.create_connection`
with a function that raises, so an accidental live probe fails loudly
instead of silently depending on network availability.

## Limitations and deferred work

See `evidence/FW-CAP-DISPATCH-004/execution_summary.md`'s "Limitations"
section: no real identity/license/maintenance data source is wired; cost/
latency/freshness figures in this proof are illustrative, not measured;
`ARCHITECTURAL_CONFLICT` has no exercised fixture case yet; the
category→function-tags table will need extending as new candidate
categories appear.
