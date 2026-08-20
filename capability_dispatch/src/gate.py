"""PROBLEM-FIRST DISPATCH GATE.

A mission may not proceed to capability selection until it states a
problem, a desired outcome, and a success metric -- guessing is never an
acceptable substitute (mission brief, verbatim: "The system may return a
structured clarification requirement instead of guessing").

This module owns the three explicitly-named MISSING_* hard-block reasons.
The remaining seven named reasons (IDENTITY_AMBIGUOUS_FOR_INSTALL,
AUTHORITY_NOT_GRANTED, LICENSE_INCOMPATIBLE, UNBOUNDED_EXECUTION_SURFACE,
SECURITY_REVIEW_FAILED, ARCHITECTURAL_CONFLICT, INSUFFICIENT_EVIDENCE) are
necessarily per-candidate or per-decision, not knowable from the mission
request alone -- dispatch.py raises those using the SAME HardBlock shape
this module defines, so every hard-block result in this system looks the
same regardless of which stage produced it. Technical failure, evidence
insufficiency, and governance rejection are kept as visibly distinct
`category` values on that shared shape, per the mission's explicit
requirement that these three must never be collapsed into one signal.
"""
from . import schema

REQUIRED_MISSION_FIELDS = (
    "problem_statement", "root_cause_hypothesis", "desired_outcome",
    "success_metric", "required_execution_surface", "authority_envelope",
)

CATEGORY_GOVERNANCE_REJECTION = "GOVERNANCE_REJECTION"
CATEGORY_EVIDENCE_INSUFFICIENCY = "EVIDENCE_INSUFFICIENCY"
CATEGORY_TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


def hard_block(reason: str, detail: str, category: str) -> dict:
    if reason not in schema.HARD_BLOCK_REASONS:
        raise ValueError(f"reason must be one of {schema.HARD_BLOCK_REASONS}")
    if category not in (CATEGORY_GOVERNANCE_REJECTION, CATEGORY_EVIDENCE_INSUFFICIENCY, CATEGORY_TECHNICAL_FAILURE):
        raise ValueError("category must be GOVERNANCE_REJECTION, EVIDENCE_INSUFFICIENCY, or TECHNICAL_FAILURE")
    return {"hard_block_reason": reason, "detail": detail, "category": category}


def check_problem_first_gate(mission_request: dict) -> dict:
    """Returns a HardBlock dict (see hard_block()) if the gate fails, or
    a normalized mission_request dict (root_cause_hypothesis/
    required_execution_surface/authority_envelope defaulted if absent,
    never silently guessed for the three MISSING_*-checked fields) if it
    passes. Callers distinguish the two return shapes by checking for the
    "hard_block_reason" key.
    """
    problem_statement = mission_request.get("problem_statement")
    if not problem_statement or not str(problem_statement).strip():
        return hard_block(
            "MISSING_PROBLEM_STATEMENT",
            "mission_request.problem_statement is empty or absent -- the system will not "
            "guess what problem this mission is trying to solve.",
            CATEGORY_EVIDENCE_INSUFFICIENCY,
        )

    desired_outcome = mission_request.get("desired_outcome")
    if not desired_outcome or not str(desired_outcome).strip():
        return hard_block(
            "MISSING_DESIRED_OUTCOME",
            "mission_request.desired_outcome is empty or absent -- the system will not "
            "guess what a successful outcome would look like.",
            CATEGORY_EVIDENCE_INSUFFICIENCY,
        )

    success_metric = mission_request.get("success_metric")
    if not success_metric or not str(success_metric).strip():
        return hard_block(
            "MISSING_SUCCESS_METRIC",
            "mission_request.success_metric is empty or absent -- the system will not "
            "guess how success would be measured.",
            CATEGORY_EVIDENCE_INSUFFICIENCY,
        )

    normalized = dict(mission_request)
    normalized.setdefault("root_cause_hypothesis", None)
    normalized.setdefault("required_execution_surface", "UNSPECIFIED")
    normalized.setdefault("authority_envelope", "NOT_GRANTED")
    return normalized


def gate_passed(result: dict) -> bool:
    return "hard_block_reason" not in result
