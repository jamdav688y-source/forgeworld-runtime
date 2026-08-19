# PROOF 001 Claims-Integrity Report

Scope: the four `ExtractedClaim` objects produced by the two proof runs
(`CLM-9c1d7a182ab0`, `CLM-88427a0e6dc8`, `CLM-bcf3d342cc58`,
`CLM-1f046b8dd70b` — see `PROOF_001_EVIDENCE_MANIFEST.md` for full context).
This report checks each claim against three integrity properties a claim
in this system must never violate.

## Property 1 — every claim traces to a specific EvidenceRelationship, never to raw candidates directly

`schema.new_extracted_claim` requires `relationship_ids` non-empty and
raises `ValueError` if called without one — a claim cannot be constructed
directly from a `CandidateSource`, only from an already-assessed
`EvidenceRelationship`. Checked for all four:

| claim | relationship it traces to | check |
|---|---|---|
| CLM-9c1d7a182ab0 | REL-fe0776e69895 (corroborates) | `evidence_references == ["REL-fe0776e69895"]` ✓ |
| CLM-88427a0e6dc8 | REL-9e5348dcabee (unrelated) | ✓ |
| CLM-bcf3d342cc58 | REL-19eea8bdd520 (contradicts) | ✓ |
| CLM-1f046b8dd70b | REL-3fdb8c2f2997 (unrelated) | ✓ |

## Property 2 — a claim's validation_status (evidence classification) matches its relationship's relationship_type exactly, via a fixed, auditable mapping

`claims.py`'s `_CLASSIFICATION_BY_RELATIONSHIP` dict is the entire
classification logic — no branch anywhere else in the codebase sets a
claim's `validation_status`:

```
corroborates    -> corroborated-claim
contradicts     -> contradicted-claim
unrelated       -> unverified-claim
near_duplicate  -> unverified-claim   (duplication says nothing about truth)
```

| claim | relationship_type | expected classification | actual validation_status | match |
|---|---|---|---|---|
| CLM-9c1d7a182ab0 | corroborates | corroborated-claim | corroborated-claim | ✓ |
| CLM-88427a0e6dc8 | unrelated | unverified-claim | unverified-claim | ✓ |
| CLM-bcf3d342cc58 | contradicts | contradicted-claim | contradicted-claim | ✓ |
| CLM-1f046b8dd70b | unrelated | unverified-claim | unverified-claim | ✓ |

4/4 correct. Committed regression coverage:
`perception/tests/test_corroboration_claims.py::TestClaimsAndEvidenceClassification`
(one test per mapping row, run against fresh fixture data each time, not
just this run's specific IDs).

## Property 3 — a contradicted-claim always blocks promotion before authority/evidence are even checked, with no bypass path

`promotion.evaluate_promotion()` checks `claim["validation_status"] ==
"contradicted-claim"` for every claim a proposal is grounded in, *first*,
before calling `governance.authority.evaluate_authority()` or
`governance.evidence.current_evidence_state()` at all:

```python
contradicted = [c for c in linked_claims if c["validation_status"] == "contradicted-claim"]
if contradicted:
    decision_obj = schema.new_promotion_decision(..., decision="DEFERRED", ...,
        authority_decision="NOT_CHECKED", evidence_state="NOT_CHECKED")
    ...
    return decision_obj
```

Verified against `CLM-bcf3d342cc58` → `PRP-bbe661178aee` →
`PRO-cbafab135709`: `decision=DEFERRED`,
`authority_decision=NOT_CHECKED`, `evidence_state=NOT_CHECKED` — proving
the short-circuit actually fired rather than merely existing in source.
There is no code path in `promotion.py`, `proposal.py`, or `schema.py`
that can set a `PromotionDecision.decision` to `PROMOTED` when any linked
claim is `contradicted-claim`: the only place `decision` is assigned is
inside `evaluate_promotion()`, and the contradiction check is the first
statement in the function body, before any variable holding a `PROMOTED`
possibility is even computed.

## Confidence values — not decorative

| claim | confidence | source |
|---|---|---|
| CLM-9c1d7a182ab0 | inherited from REL-fe0776e69895 (0.8 — two-independent-domains default) | `proposal.propose_capability` reuses `claim["confidence"]`, which reuses `relationship["confidence"]` |
| CLM-88427a0e6dc8 | 0.3 (single-domain default) | same chain |
| CLM-bcf3d342cc58 | 0.8 (contradicts, still two independent domains observed) | same chain |
| CLM-1f046b8dd70b | 0.3 | same chain |

Confidence is not re-derived at the claim layer independently of the
relationship it came from — it is carried through unchanged, so a claim's
stated confidence can always be traced back to the exact independence
computation that produced it (see `corroboration.py`'s
`assess_corroboration()`: `confidence=0.8 if relationship_type != "unrelated" else 0.3`).

## What this report does not claim

This report verifies **structural** integrity — that the classification
mapping is followed exactly and that the contradiction gate cannot be
bypassed in code. It does not claim the underlying contradiction-detection
*heuristic* is semantically sophisticated: `corroboration.py`'s
`CONTRADICTION_MARKERS` keyword list (`{"false", "hoax", "debunked",
"denied", "not true", "incorrect", "fake", "disputed"}`) is a small,
auditable heuristic in the same spirit as `whatsapp/src/classify.py`'s
keyword lists, not a claim of semantic understanding — see
`corroboration.py`'s module docstring, which says so explicitly.
