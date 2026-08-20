# FW-CAP-DISPATCH-004 — Execution Summary

## Mission

> Integrate the supplied capability-candidate intelligence into
> ForgeWorld's canonical database and systemic dispatch architecture.

Branch: `feature/fw-cap-dispatch-004`, based on `claude/perception-gateway`
(PR #5) at `00f353fb4d1fedbd7fe45d1d213ac3bf62447ae4` — see
`baseline.json` for why (the mission's own required canonical components —
Execution Ledger, Evidence gates, Authority Model — only exist on that
unmerged branch, not on `main`).

## Revision (2026-08-20): authoritative artifacts received and integrated

`FW-CAP-DISPATCH-004.json` and `FW-CAP-DISPATCH-004.md` were subsequently
committed directly to this branch by the repository owner at
`611b41ef8cc4c1bd1837c054aa69a8183e17fe26`, under
`capability_dispatch/intake/`. Both files' sha256 hashes were
independently recomputed in this session and matched the declared values
exactly (see `artifact_validation.json`'s `superseding_update_2026_08_20`).

A **second, real-shape ingester** (`capability_dispatch/src/authoritative_intake.py`)
was written because the authoritative packet's JSON shape genuinely
differs from the synthetic fixture's: `capability_candidates[].name`/`.category`
instead of `candidates[].observed_name`/`.observed_category`, no
`candidate_count` field at all (derived and stated as derived), and
`canonical_hint` values arriving as bare `github.com/owner/repo` strings
with no scheme (preserved raw, with a separately-recorded
`canonical_hint_normalized` + `canonical_hint_normalization_method` —
never silently rewritten in place).

```
SourceObservation SRC-236f3514f9c4, sha256=8252cf225ad9017c..., 42 candidates (derived)
SourceObservation SRC-0ce84596310f (the .md companion), sha256=b696b375f3921b18...

42/42 candidates ingested, 0 duplicates, epistemic floor confirmed for all 42.
9/42 carry a canonical_hint (all bare "github.com/owner/repo", normalized with an
assumed https:// scheme, raw value preserved unmodified).

Identity resolution: FixtureIdentityResolver({}) (EMPTY -- no live network/registry
lookup performed this mission) -> 42/42 UNAVAILABLE. This is the honest, correct
outcome given the offline constraint, not a defect -- the artifact's own .md states
"Canonical identity resolution: incomplete".

Overlap analysis: 42/42 UNRESOLVED, as a direct consequence of the above (overlap.py's
identity gate fires before any registry comparison is attempted for a non-VERIFIED candidate).

Dispatch (no mission fields supplied): DEC-380ce2c1747e HARD_BLOCKED / MISSING_PROBLEM_STATEMENT
Dispatch (illustrative mission_request, required_capabilities = the packet's own 8
observed categories): DEC-601c63567bdb NO_SUFFICIENT_CANDIDATE
  4 of 8 required categories covered via REUSE against the EXISTING registry
  (python x3, airtable, claude_code x2, chatgpt -- no new candidate needed);
  remaining categories uncovered because no candidate in this packet could be
  verified without live network access this mission does not have.
```

Full raw objects: `authoritative_dispatch_output.json` in this directory.
Full per-report detail: `candidate_import_report.json`,
`identity_resolution_report.json`, `overlap_analysis_report.json`,
`claims_integrity_report.json` — each now split into an
`authoritative_*`/`AUTHORITATIVE_MISSION_SOURCE` section (this packet) and
a `test_fixture_ingestion`/`TEST_FIXTURE` section (the synthetic packet,
prohibited from serving as mission-source evidence from this revision
forward, retained only for deterministic offline test coverage).

New regression coverage: `capability_dispatch/tests/test_authoritative_intake.py`
(hash-pinned against the real committed files, so a future accidental edit
to `capability_dispatch/intake/*.json/.md` fails CI immediately).

### Original (pre-revision) synthetic-substitute rationale, preserved for the record

`FW-CAP-DISPATCH-004.json` and `FW-CAP-DISPATCH-004.md` were never
supplied to this mission — confirmed by exhaustive filesystem search (see
`artifact_validation.json`). A clearly-labeled synthetic substitute
(`capability_dispatch/fixtures/FW-CAP-DISPATCH-004.synthetic.json`) was
built instead, modeled on the mission brief's own description of the
source material (screenshots with changing star counts and unresolved
shortened links). That version of this report never claimed the named
files were used, and this revision does not retroactively claim the
synthetic run was ever anything but a stand-in.

## What was built

Twelve required functions, each in its own module under
`capability_dispatch/src/`, extending existing canonical components rather
than duplicating them (full table: `repository_reuse_map.json`):

| Function | Module | Extends |
|---|---|---|
| SOURCE OBSERVATION ingestion | `ingest.py` | perception's governed-ingest pattern |
| CANDIDATE IDENTITY RESOLUTION | `identity.py` | perception's provider-neutral pattern |
| REGISTRY OVERLAP ANALYSIS | `overlap.py` | `capabilities/discover.py`, perception's EvidenceRelationship shape |
| PROBLEM-FIRST DISPATCH GATE | `gate.py` | — (net new, per confirmed gap) |
| DYNAMIC DISPATCH ENGINE | `dispatch.py` | `router/mission_router.py` (imported, not reimplemented) |
| CONTEXT COMPILATION | `context.py` | `governance/authority.py`'s `load_policies()` |
| DISPATCH LEARNING RECORD | `learning.py` | `router/record_outcome.py` (writes through it) |
| THIRD-PARTY SAFETY BOUNDARY | `safety_boundary.py` | — (net new, per confirmed gap) |

## Proof run (real code, TEST_FIXTURE synthetic input — historical, pre-revision)

One full pipeline run against the synthetic fixture, decided by
`human:jamdav688y@gmail.com`, `authority_envelope=GRANTED_BOUNDED`:

```
SourceObservation SRC-be1b02776ff8, sha256=16bf1f80823e1a05..., 5 candidates

CAP-9350646f92f8  SYNTHETIC-gitleaks-clone          VERIFIED    UNIQUE_GAP          -> SANDBOX_PROBE
CAP-828d3059ff33  SYNTHETIC-python-wrapper-cli       VERIFIED    FUNCTIONAL_DUPLICATE -> DUPLICATE
CAP-466f2d5fa7ad  SYNTHETIC-shortlink-mystery-tool   AMBIGUOUS   UNRESOLVED          -> BLOCK
CAP-31cf4841902f  SYNTHETIC-unbounded-shell-agent    VERIFIED    PARTIAL_OVERLAP     -> BLOCK (UNBOUNDED_EXECUTION_SURFACE, overrides ADAPT)
CAP-8f97b2df588f  SYNTHETIC-unknown-tool-xyz         UNAVAILABLE UNRESOLVED          -> BLOCK

DispatchDecision DEC-3b3aacf20d9a: DISPATCHED
  selected_set: [{candidate_id: CAP-9350646f92f8, disposition: SANDBOX_PROBE}]
  (the smallest sufficient set for required_capabilities=['secret_scanning_cli'])

Hard-block demonstrations:
  DEC-eddd090d006c: HARD_BLOCKED / MISSING_PROBLEM_STATEMENT
  DEC-a85503015d90: HARD_BLOCKED / MISSING_SUCCESS_METRIC

DispatchLearningRecord LRN-b21b140e1a0d: evidence_sufficiency=SUPPORTED,
  written through router.record_outcome.record() into capabilities/history.jsonl
  (isolated tmp path during this proof run -- see rollback_plan.md)
```

A second scenario (`RUN-REUSE-A`, exercised in manual verification, not
re-run for this file) confirmed the smallest-sufficient-set logic also
recognizes when an *already-registered* capability satisfies a
requirement with **no new candidate at all**: `required_capabilities=['scripting_utility']`
resolved to `disposition: REUSE`, `candidate_id: null`,
`existing_capability_id: 'python'`.

Full raw objects: `dispatch_proof_output.json` in this directory.

## Execution Ledger coverage

```
CAPTURE: 1   HASH: 2   IDENTITY_RESOLUTION: 10   REGISTRY_OVERLAP: 5
DISPATCH_EVALUATION: 5   DISPATCH_DECISION: 3   CONTEXT_COMPILATION: 1
DISPATCH_LEARNING: 1
```
(19 records this run, all `system=capability_dispatch`, in the same
`whatsapp/ledgers/execution_ledger.jsonl` file the WhatsApp membrane and
Perception Gateway already write into.)

## A real bug found and fixed mid-mission

`dispatch.score_candidate()` originally called
`capabilities.discover.probe_all()` unconditionally — which performs a
real TCP connection attempt for the `github` registry entry
(`api.github.com:443`). This would have violated the mission's own "Do
not use live external repositories in unit tests" / CI "must operate
without requiring live external network access" requirements. Fixed by
making `reachability_state` an explicit, optional parameter threaded
through `score_candidate` → `evaluate_candidate` → `run_dispatch`; every
test in `capability_dispatch/tests/` supplies a deterministic fixture
dict and additionally monkeypatches `socket.create_connection` to raise
if anything ever tries a real connection (see `tests/base.py`). Verified:
the full test suite passes with that block active.

A second gap was found and fixed during test-writing, not before: the
initial `select_smallest_sufficient_set()` only ever considered newly
ingested candidates, never an already-registered capability that might
already satisfy a requirement outright — meaning the engine could recommend
installing something redundant even when nothing needed to be added at
all. Fixed by checking `capabilities/registry.json` for a covering
capability first, only falling through to candidate evaluation for
requirements the registry doesn't already cover.

## Test results

```
capability_dispatch/tests/test_dispatch_matrix.py: 26 passed
  (TEST-DISPATCH-001 through TEST-DISPATCH-012, all 12 named scenarios,
   several with multiple assertions each -- see dispatch_test_results.xml)
tests/governance: 60 passed (unmodified)
whatsapp/tests: 60 passed (unmodified)
perception/tests: 69 passed (unmodified)
```

No test run modifies a tracked repository file (`governance/evidence_log.jsonl`,
`router/decisions.jsonl`, `capabilities/history.jsonl` all verified clean
via `git status --porcelain` before and after every test invocation in
this session).

## Limitations and deferred work

- Cost/latency/freshness figures on `DispatchProfile` objects in this
  proof are hand-authored for the synthetic fixture, not measured from
  any real execution — the confidence arithmetic over them is real, but
  its inputs are illustrative, not empirical.
- No real identity resolver, license database, or maintenance-activity
  API is wired (`UnwiredRegistryIdentityResolver` documents the hook
  point, raises `NotImplementedError`).
- `SANDBOX_PROBE` disposition is fully computed and recorded, but this
  mission grants no execution authority — no candidate is ever actually
  run, sandboxed or otherwise (see `THIRD_PARTY_SAFETY_BOUNDARY.md`).
- The category → function-tags mapping (`overlap.py`'s
  `CATEGORY_FUNCTION_TAGS`) is a small, hand-maintained table, the same
  posture as `whatsapp/src/classify.py`'s keyword lists — not a claim of
  semantic understanding, and it will need extending as new candidate
  categories appear.

## Completion status

**ACTUAL_ARTIFACT_INTEGRATION_COMPLETE** (this revision) — supersedes the
prior **INTEGRATION_COMPLETE** marker, which was scoped to the synthetic
substitute only. See the top-level PR #6 revision commit for exact test
totals and CI verification.
