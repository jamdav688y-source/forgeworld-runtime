"""The promotion gate.

Execution success does not equal promotion. Neither does strong evidence,
by itself. Promotion requires its own, independent authority decision
*and* its own evidence threshold -- see mission section 11's worked
example: BUILD succeeded + TESTS passed + DEVICE validation passed + TAG
pushed still does not imply PRODUCTION deployment is authorized.

This module never inspects execution results directly -- it only takes an
evidence state (from evidence.current_evidence_state) and an authority
decision (from authority.evaluate_authority) as independent inputs,
because collapsing "it worked" and "it may be promoted" into one boolean
is exactly what this mission prohibits.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from governance.authority import AuthorityDecision
from governance.types import AuthorityState, AUTONOMOUS_EXECUTABLE_STATES, EvidenceState, evidence_at_least

# Generic lifecycle-tier -> minimum evidence defaults. Callers should
# prefer passing an explicit `required_evidence_state` derived from the
# matched authority policy's `evidence_required` field (see
# governance/policy_defaults.json) when one exists; these are fallbacks
# for tiers with no specific policy.
DEFAULT_EVIDENCE_REQUIREMENTS = {
    "CANDIDATE": EvidenceState.OBSERVED,
    "SUPPORTED": EvidenceState.SUPPORTED,
    "VALIDATED": EvidenceState.VALIDATED,
    "RELEASED": EvidenceState.VALIDATED,
    "PRODUCTION": EvidenceState.VALIDATED,
    "INSTITUTIONALIZED": EvidenceState.INSTITUTIONALIZED,
}


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    reason: str
    artifact_id: str
    from_state: str
    to_state: str
    required_evidence_state: EvidenceState
    observed_evidence_state: EvidenceState
    authority_decision: str
    missing: tuple
    decided_at: str


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def can_promote(
    artifact_id: str,
    from_state: str,
    to_state: str,
    evidence_state: EvidenceState,
    authority_decision: AuthorityDecision,
    actor_kind: str,
    required_evidence_state: Optional[EvidenceState] = None,
    risk: str = "MEDIUM",
) -> PromotionDecision:
    """Independent promotion gate.

    `actor_kind` must be "human" or "agent". An agent can never satisfy a
    HUMAN_ONLY authority decision, no matter how strong the evidence --
    this is what keeps PROMOTE_RELEASE human-controlled even after every
    upstream check passed.
    """
    if actor_kind not in ("human", "agent"):
        raise ValueError(f"actor_kind must be 'human' or 'agent', got {actor_kind!r}")

    missing = []

    if actor_kind == "agent":
        authority_ok = authority_decision.decision in AUTONOMOUS_EXECUTABLE_STATES
    else:  # human
        authority_ok = authority_decision.decision in AUTONOMOUS_EXECUTABLE_STATES | {AuthorityState.HUMAN_ONLY}

    if not authority_ok:
        missing.append(f"authority={authority_decision.decision.value} (actor_kind={actor_kind})")

    req_evidence = required_evidence_state or DEFAULT_EVIDENCE_REQUIREMENTS.get(to_state, EvidenceState.OBSERVED)
    if not evidence_at_least(evidence_state, req_evidence):
        missing.append(f"evidence={evidence_state.value} < required={req_evidence.value}")

    allowed = len(missing) == 0
    reason = (
        "Promotion allowed: independent authority and evidence thresholds both satisfied."
        if allowed
        else f"Promotion denied: {'; '.join(missing)}"
    )

    return PromotionDecision(
        allowed=allowed,
        reason=reason,
        artifact_id=artifact_id,
        from_state=from_state,
        to_state=to_state,
        required_evidence_state=req_evidence,
        observed_evidence_state=evidence_state,
        authority_decision=authority_decision.decision.value,
        missing=tuple(missing),
        decided_at=_now(),
    )
