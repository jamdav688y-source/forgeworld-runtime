# FORGEWORLD VALIDATION 001 — Report

This is an evidence demonstration, not a promotional artifact. Every claim below is
tagged as a SOURCE FACT (verifiable directly against the source screenshot),
a FORGEWORLD INTERPRETATION (a reading supplied by the operator running this
validation), a TESTABLE CLAIM (something the pipeline in this repo actually
checked, mechanically, this run), or an UNPROVEN CLAIM (explicitly not
demonstrated here). Full evidence lives in `VALIDATION_001.json`, hashes in
`VALIDATION_001_MANIFEST.md`, and scored metrics in `VALIDATION_001_METRICS.json`.

## Validation question

> Can ForgeWorld convert an ordinary external exchange into a traceable,
> governed action without losing the connection to its originating evidence?

This report answers that question against one real exchange, one pipeline run,
run once, today.

## The seven questions this artifact must answer

### 1. What triggered this validation?

**SOURCE FACT.** A LinkedIn DM screenshot between "Lorenzo Asnaghi" and "James
Davis," supplied by the user in this session as a chat attachment. The file was
verified to be a genuine 1080x2388 PNG (`file` reports `PNG image data, 1080 x
2388, 8-bit/color RGBA`), preserved byte-for-byte at
`validation/VALIDATION_001/source/lorenzo_asnaghi_linkedin_exchange.png`, and
hashed:

```
sha256: 4259ef3500ba7ec11442c28ef6c9eb0a412f1a24f00edf5c923197235a5fdfe9
```

Lorenzo Asnaghi's messages (transcribed verbatim in `source_record.json`,
lines L1 and L3) ask to be kept posted on "how it develops as you get more
real-world feedback and data" and "what you learn once there's more real-world
data behind it." That is the external signal this validation exists to answer.
It is curiosity and a request to be kept informed — **not** an endorsement of
ForgeWorld, and the screenshot never uses the word "ForgeWorld."

### 2. What did ForgeWorld infer?

**FORGEWORLD INTERPRETATION**, explicitly labeled as such at the point it
happens (`requirement.json`, `statement_classification: FORGEWORLD_INTERPRETATION`).
Two inferences were made, both authored by the operator (this Claude session)
in `pipeline/annotations.json` — not derived by an automated NLP extraction
system:

- **Requirement** (from L1/L3, interpretation applied — the source never names
  ForgeWorld): "Show what happens when ForgeWorld encounters more real-world
  feedback and data."
- **Commitment** (from L2, James Davis's own words, closer to source fact):
  "Return with what actually held up, failed, and changed once real-world
  evidence accumulates."

### 3. What action resulted?

**TESTABLE CLAIM, PASS.** A mission record, `VALIDATION-001`, was generated
deterministically from the commitment (`mission.json`, produced by
`pipeline/run_pipeline.py:step_structure`, template fill only, no free
generation). It was then routed through this repository's existing capability
router (`router/mission_router.py`, not reimplemented for this task) and
selected `claude_code` as the reachable capability
(`route_decision.json`, appended for real to `router/decisions.jsonl`). The
outcome was recorded to `capabilities/history.jsonl` via the repo's existing
`router/record_outcome.py` (`track_result.json`).

### 4. What evidence supports that action?

**TESTABLE CLAIM, PASS.** Every object in the chain carries an explicit
`source_ref` or `*_ref` pointer back to the object before it, and a
`statement_classification` field marking it SOURCE_FACT or
FORGEWORLD_INTERPRETATION. The `GOVERN` pipeline step
(`governance_result.json`) mechanically checked that those fields and
references are present and correctly linked — it did not just assume they
were.

### 5. Can the action be traced back to its source?

**TESTABLE CLAIM, PASS — this is the central proof.** `pipeline/run_pipeline.py`'s
`run_trace()` walks backward:

```
MISSION (VALIDATION-001)
  -> COMMITMENT (COM-VALIDATION-001)
  -> REQUIREMENT (REQ-VALIDATION-001)
  -> ORIGINAL EXCHANGE (source_record.json line L1)
  -> SOURCE FILE (sha256 re-verified against the PNG on disk, right now)
```

Each hop is a mechanical check (reference resolution or, at the last hop,
recomputing the source file's SHA-256 and comparing it to the value recorded
at capture time), not a narrative claim. Result: `trace_result.json`,
`overall_verdict: PASS`, all 4 hops resolved.

### 6. What actually passed?

See `VALIDATION_001_METRICS.json` for the scored list with evidence pointers.
Summary, all measured this run:

| Metric | Verdict |
|---|---|
| source preserved | PASS |
| source hash verified | PASS |
| requirement extracted | PASS |
| commitment extracted | PASS |
| mission generated | PASS |
| governance separation check | PASS |
| mission routed to reachable capability | PASS |
| outcome recorded to capability history | PASS |
| backward provenance trace successful | PASS |
| retrieval successful | **NOT TESTED** |
| processing time measured | PASS (20.1ms total pipeline time) |

### 7. What remains unproven?

**UNPROVEN CLAIM.**

- **Single-case demonstration.** One exchange, one pipeline run. No claim of
  generalization.
- **Human interpretation still involved.** The requirement/commitment mapping
  in `pipeline/annotations.json` was authored by the operator running this
  validation, not derived by an automated extraction model. This pipeline
  demonstrates *governed structure and traceability* once that mapping
  exists — it does not demonstrate automated natural-language extraction.
- **Retrieval was not tested.** No separate query/retrieval mechanism was
  built or exercised against the stored records this run — marked NOT TESTED,
  not assumed to pass.
- **Business impact not yet established.** No outcome beyond the artifacts in
  this directory has been measured.
- **External replication required.** No independent party has re-run this
  pipeline against this or any other source.

## What this artifact is not claiming

It is not claiming Lorenzo Asnaghi endorsed ForgeWorld — his messages express
curiosity and a request to be kept posted, nothing more, and are reproduced
verbatim in `source_record.json` for anyone to check. It is not claiming the
requirement/commitment extraction was automatic — Scene 9 of the video and
this report both say plainly that a human (this session) authored that
mapping. It is not claiming any of ForgeWorld's other doctrine subsystems
(council review, faction memory, reputation) executed here — only the router,
capability registry, and this new pipeline did, and only those are represented
as evidence.

## Reproducing this run

```
python3 validation/VALIDATION_001/pipeline/run_pipeline.py
python3 validation/VALIDATION_001/pipeline/build_scenes.py
python3 evolution_clip/render.py validation/VALIDATION_001/scenes.json \
    validation/VALIDATION_001/render --mp4 validation/VALIDATION_001/VALIDATION_001.mp4
python3 validation/VALIDATION_001/pipeline/build_evidence_package.py
```

Re-running will re-verify the source hash against the live PNG, re-run the
backward trace, and append new entries to `router/decisions.jsonl` and
`capabilities/history.jsonl` (both are append-only logs by design — see
`router/record_outcome.py`'s docstring).
