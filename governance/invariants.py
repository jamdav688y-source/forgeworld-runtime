"""Executable capability-design invariants for ForgeWorld.

These are architectural invariants, not physical laws.  They compress four
cross-cutting governance requirements into one reusable evaluator while
preserving each result independently for audit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from .types import AUTONOMOUS_EXECUTABLE_STATES, AuthorityState, EvidenceState, EVIDENCE_STATE_ORDER


class InvariantState(str, Enum):
    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class InvariantResult:
    invariant_id: str
    state: InvariantState
    reason: str
    evidence_references: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state.value
        data["evidence_references"] = list(self.evidence_references)
        return data


EXECUTABLE_DISPOSITIONS = frozenset({"SANDBOX_PROBE"})
PROMOTION_DISPOSITIONS = frozenset({"INSTALL", "PROMOTE", "PRODUCTION"})


def _authority_state(value) -> AuthorityState | None:
    try:
        return value if isinstance(value, AuthorityState) else AuthorityState(value)
    except (TypeError, ValueError):
        return None


def evaluate_capability_design_invariants(
    *,
    capability_available: bool,
    disposition: str,
    authority_state,
    supporting_evidence_state: EvidenceState,
    derived_evidence_state: EvidenceState,
    execution_succeeded: bool = False,
    promotion_requested: bool = False,
    promotion_authorized: bool = False,
    evidence_references: Iterable[str] = (),
) -> list[dict]:
    """Evaluate the four invariants without collapsing them to one score.

    The caller may block on violations, but must retain every result.  Unknown
    authority and evidence states fail closed as UNRESOLVED.
    """
    refs = tuple(evidence_references)
    executable = disposition in EXECUTABLE_DISPOSITIONS
    authority = _authority_state(authority_state)
    results: list[InvariantResult] = []

    results.append(InvariantResult(
        "FW-INV-CAPABILITY-001",
        InvariantState.SATISFIED if capability_available else InvariantState.VIOLATED,
        "A declared capability is available for the proposed action."
        if capability_available else
        "No declared capability supports the proposed action; execution is forbidden.",
        refs,
    ))

    if not executable:
        results.append(InvariantResult(
            "FW-INV-AUTHORITY-002", InvariantState.NOT_APPLICABLE,
            f"Disposition {disposition!r} is non-executable; no execution authority is consumed.", refs,
        ))
    elif authority is None:
        results.append(InvariantResult(
            "FW-INV-AUTHORITY-002", InvariantState.UNRESOLVED,
            "Authority state is missing or unknown; executable disposition must fail closed.", refs,
        ))
    else:
        granted = authority in AUTONOMOUS_EXECUTABLE_STATES
        results.append(InvariantResult(
            "FW-INV-AUTHORITY-002",
            InvariantState.SATISFIED if granted else InvariantState.VIOLATED,
            "Specific authority covers this executable disposition."
            if granted else
            f"Capability does not imply permission; authority state {authority.value} forbids autonomous execution.",
            refs,
        ))

    try:
        supporting_rank = EVIDENCE_STATE_ORDER.index(supporting_evidence_state)
        derived_rank = EVIDENCE_STATE_ORDER.index(derived_evidence_state)
        evidence_state = InvariantState.SATISFIED if derived_rank <= supporting_rank else InvariantState.VIOLATED
        evidence_reason = (
            "Derived claims do not exceed the strength of their supporting evidence."
            if evidence_state == InvariantState.SATISFIED else
            f"Evidence-strength inflation detected: {supporting_evidence_state.value} support cannot yield "
            f"{derived_evidence_state.value} derived claims."
        )
    except (ValueError, AttributeError):
        evidence_state = InvariantState.UNRESOLVED
        evidence_reason = "Evidence strength could not be ordered; downstream claims must fail closed."
    results.append(InvariantResult("FW-INV-EVIDENCE-003", evidence_state, evidence_reason, refs))

    if not promotion_requested:
        promotion_state = InvariantState.NOT_APPLICABLE
        promotion_reason = (
            "Execution success does not imply promotion; no promotion transition was requested."
            if execution_succeeded else "No promotion transition was requested."
        )
    elif promotion_authorized:
        promotion_state = InvariantState.SATISFIED
        promotion_reason = "Promotion has an independent authorization decision."
    else:
        promotion_state = InvariantState.VIOLATED
        promotion_reason = "Execution or implementation cannot self-promote without independent promotion authority."
    results.append(InvariantResult("FW-INV-PROMOTION-004", promotion_state, promotion_reason, refs))

    return [result.to_dict() for result in results]


def invariants_permit_execution(results: Iterable[dict]) -> bool:
    """Only SATISFIED/NOT_APPLICABLE results permit downstream execution."""
    return all(r.get("state") in {InvariantState.SATISFIED.value, InvariantState.NOT_APPLICABLE.value} for r in results)
