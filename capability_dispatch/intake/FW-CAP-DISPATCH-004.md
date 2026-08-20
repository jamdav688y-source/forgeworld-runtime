# FW-CAP-DISPATCH-004 — Dynamic Capability Dispatch Intake

## Systemic change

The resource list is not an installation queue. It is a mutable observation source that produces capability candidates. The strategy post supplies the controlling dispatch rule: define the problem, root-cause hypothesis, desired outcome, and success metric before selecting a tool.

The resulting runtime sequence is:

```text
OBSERVATION
→ CANDIDATE EXTRACTION
→ IDENTITY RESOLUTION
→ OVERLAP ANALYSIS
→ SECURITY / LICENSE / MAINTENANCE REVIEW
→ SANDBOX PROBE
→ CAPABILITY EVIDENCE
→ REGISTRY DECISION
→ MISSION-TIME DISPATCH
→ EXECUTION EVIDENCE
→ ROUTING-POLICY UPDATE
```

## Dispatch behavior

At mission time the router must assemble the smallest sufficient working set rather than load every available repository, skill, or connector. It evaluates candidates against the problem, required capability, available execution surface, authority envelope, evidence strength, risk, cost, overlap, and reversibility.

Popularity and star counts are discovery signals only. They do not establish identity, fitness, safety, licensing, maintenance quality, or architectural compatibility.

## Database binding

Bind the intake packet to existing canonical entities wherever they exist:

- `VisualObservation` or equivalent: screenshot identity and provenance.
- `CapabilityCandidate`: one record per extracted resource.
- `EvidenceRelationship`: links candidates and strategy signals to source observations.
- `CapabilityRegistry`: only after verification and promotion.
- `AuthorityModel`: execution surface and allowed side effects.
- `ExecutionLedger`: dispatch decision, selected capability set, observed result, cost, failure, and rollback.

If these entities are supplied by PR #5 or another unmerged branch, retain this artifact as an ingest packet until that dependency is available. Do not create a competing database on `main`.

## Learning loop

Every dispatch produces a comparison between predicted and observed utility. That delta updates routing evidence, not global truth. Repeated validated executions may improve a candidate's dispatch confidence; popularity alone may not.

## Current disposition

- Source capture: complete.
- Candidate transcription: complete with uncertainty.
- Canonical identity resolution: incomplete.
- Repository inspection: limited; current `main` exposes the Phone Node baseline, while richer architecture remains outside the visible default branch.
- Installation: prohibited pending verification.
- Production promotion: not eligible.

**STATUS: CANDIDATE_INGEST_COMPLETE**
