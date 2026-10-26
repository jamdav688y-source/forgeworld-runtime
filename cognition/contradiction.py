"""FW-COGNITIVE-R2-001 (B): Contradiction Memory -- read-only assessment of
CONTRADICTION records.

A CONTRADICTION record (cxp KIND_CONTRADICTION) names 2-16 competing claims,
derives from exactly those claims, states the conditions that would resolve
it, and carries no truth status of its own. Its STATUS is never stored: it
is computed here, on demand, from what the exchange holds.

    OPEN                     no claim has an admissible VERIFIED result.
    RESOLVED                 exactly one claim has an admissible VERIFIED
                             result, no other claim does, and that claim has
                             no admissible REFUTED/CONTESTED result.
    CONFLICTING_VERIFICATION admissible results disagree (two claims
                             verified, or one claim both verified and
                             refuted/contested): needs human escalation.
    VOID                     the contradiction or one of its claims was
                             erased.

What NEVER moves a contradiction out of OPEN: the number of records
restating a claim, the number of independent sources behind it, how many
derived claims (model outputs included) agree with it, or refutation of
every other claim. Those are reported under non_admissible_signals so a
reader can see them, and so a test can prove they were ignored.

Admissibility is decided by a ResolutionPolicy the CALLER supplies. With no
policy, every verification result is inadmissible and nothing can resolve.
The policy names the human who approved it (approved_by); CXP records that
name but cannot authenticate it -- the same honesty boundary
evidence_envelope documents for its AuthorityVerifier. A policy governs
which verification counts as knowledge; it grants no execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from cognition import cxp, lineage

OPEN = "OPEN"
RESOLVED = "RESOLVED"
CONFLICTING_VERIFICATION = "CONFLICTING_VERIFICATION"
VOID = "VOID"

NOT_ADMISSIBLE_NO_POLICY = "NO_POLICY"
NOT_ADMISSIBLE_ERASED = "ERASED"
NOT_ADMISSIBLE_PROVENANCE = "PROVENANCE_NOT_ADMISSIBLE"
NOT_ADMISSIBLE_METHOD = "METHOD_NOT_ADMISSIBLE"

_POLICY_PROVENANCE = (cxp.HUMAN_ASSERTED, cxp.AUTHORIZED_CONCLUSION)


class ContradictionError(Exception):
    pass


@dataclass(frozen=True)
class ResolutionPolicy:
    policy_id: str
    approved_by: str
    admissible_provenance: tuple
    admissible_methods: tuple

    def __post_init__(self):
        cxp._validate_identifier(self.policy_id, "policy_id")
        cxp._validate_identifier(self.approved_by, "approved_by")
        if not self.admissible_provenance or set(self.admissible_provenance) - set(_POLICY_PROVENANCE):
            raise ContradictionError(f"admissible_provenance must be a non-empty subset of {_POLICY_PROVENANCE}")
        if not self.admissible_methods or not all(isinstance(m, str) and m for m in self.admissible_methods):
            raise ContradictionError("admissible_methods must be non-empty strings")

    @property
    def grants_execution_authority(self) -> bool:
        return False


def _admissibility(result: dict, policy) -> str:
    if result["erased"]:
        return NOT_ADMISSIBLE_ERASED
    if policy is None:
        return NOT_ADMISSIBLE_NO_POLICY
    if result["provenance"] not in policy.admissible_provenance:
        return NOT_ADMISSIBLE_PROVENANCE
    if result.get("verification_method") not in policy.admissible_methods:
        return NOT_ADMISSIBLE_METHOD
    return "ADMISSIBLE"


def contradictions_for(exchange, claim_id: str) -> tuple:
    """Ids of every recorded contradiction naming claim_id."""
    return tuple(m["record_id"] for m in exchange.all_record_metadata()
                 if claim_id in (m.get("contradiction_claims") or ()))


def assess(exchange, contradiction_id: str, policy=None, clearance: str = cxp.PRIV_INTERNAL) -> dict:
    meta = exchange.record_metadata(contradiction_id)
    if meta is None or meta["kind"] != cxp.KIND_CONTRADICTION:
        raise ContradictionError(f"{contradiction_id} is not an accepted CONTRADICTION")
    everything = exchange.all_record_metadata()
    claim_ids = meta["contradiction_claims"]
    record = exchange.get_record(contradiction_id)

    claims, verified, opposed = [], set(), set()
    for claim_id in claim_ids:
        claim_meta = exchange.record_metadata(claim_id)
        trace = lineage.trace(exchange.record_metadata, claim_id, clearance)
        admissible_for, admissible_against, inadmissible = [], [], []
        for result in everything:
            if result["kind"] != cxp.KIND_VERIFICATION_RESULT or result.get("verification_target") != claim_meta["content_id"]:
                continue
            verdict = _admissibility(result, policy)
            if verdict != "ADMISSIBLE":
                inadmissible.append({"record_id": result["record_id"], "reason": verdict})
            elif result["verification_outcome"] == cxp.VER_VERIFIED:
                admissible_for.append(result["record_id"])
            else:
                admissible_against.append(result["record_id"])
        if admissible_for:
            verified.add(claim_id)
        if admissible_against:
            opposed.add(claim_id)
        restatements = [m["record_id"] for m in everything
                        if claim_id in m["derived_from"] and m["kind"] != cxp.KIND_CONTRADICTION]
        claims.append({
            "claim_id": claim_id,
            "erased": claim_meta["erased"],
            "epistemic_class": trace["epistemic_class"],
            "lineage": {"observation_roots": trace["observation_roots"], "sources": trace["sources"],
                        "independent_origin_count": trace["independent_origin_count"]},
            "supporting_evidence": {"verification_results": sorted(admissible_for)},
            "opposing_evidence": {"competing_claims": sorted(c for c in claim_ids if c != claim_id),
                                  "verification_results": sorted(admissible_against)},
            "non_admissible_signals": {
                "restatement_count": len(restatements),
                "independent_origin_count": trace["independent_origin_count"],
                "inadmissible_verification_results": sorted(inadmissible, key=lambda r: r["record_id"]),
            },
        })

    if meta["erased"] or any(c["erased"] for c in claims):
        status, resolved_in_favor_of = VOID, None
    elif len(verified) > 1 or verified & opposed:
        status, resolved_in_favor_of = CONFLICTING_VERIFICATION, None
    elif len(verified) == 1:
        status, resolved_in_favor_of = RESOLVED, next(iter(verified))
    else:
        status, resolved_in_favor_of = OPEN, None

    resolution_basis = None
    if status == RESOLVED:
        winner = next(c for c in claims if c["claim_id"] == resolved_in_favor_of)
        resolution_basis = {"verification_results": winner["supporting_evidence"]["verification_results"],
                            "policy_id": policy.policy_id, "policy_approved_by": policy.approved_by}

    return {
        "contradiction_id": contradiction_id,
        "status": status,
        "resolved_in_favor_of": resolved_in_favor_of,
        "resolution_basis": resolution_basis,
        "resolution_conditions": None if record is None else record.payload()["resolution_conditions"],
        "policy_id": None if policy is None else policy.policy_id,
        "claims": claims,
        "grants_execution_authority": False,
    }
