#!/usr/bin/env python3
"""Deterministic minimum-safe architecture selector for ForgeWorld.

This module selects an architecture class from mission properties, not from
framework or provider preference.  Evidence maturity caps the authority that
may be granted; when a mission needs more architecture than the available
evidence authorizes, the result is evidence_blocked rather than silently
escalated.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


ARCHITECTURES = {
    1: "simple_chatbot",
    2: "rag_application",
    3: "single_agent",
    4: "multi_agent_system",
    5: "autonomous_workflow",
    6: "enterprise_agent",
}

EVIDENCE_AUTHORITY_CAP = {
    "none": 1,
    "hypothesis": 2,
    "prototype": 3,
    "validated": 5,
    "operational": 6,
}


@dataclass(frozen=True)
class MissionArchitectureContext:
    grounding_required: bool = False
    tool_actions: bool = False
    persistent_memory: bool = False
    parallel_specialists: bool = False
    event_triggered: bool = False
    self_correction: bool = False
    consequential_actions: bool = False
    regulated_or_sensitive: bool = False
    multi_tenant: bool = False
    enterprise_scale: bool = False
    risk: str = "low"
    evidence_level: str = "none"
    requested_level: Optional[int] = None
    controls: List[str] = field(default_factory=list)


def _required_level(context: MissionArchitectureContext) -> int:
    level = 1
    if context.grounding_required:
        level = max(level, 2)
    if context.tool_actions or context.persistent_memory:
        level = max(level, 3)
    if context.parallel_specialists:
        level = max(level, 4)
    if context.event_triggered or context.self_correction:
        level = max(level, 5)
    if context.regulated_or_sensitive or context.multi_tenant or context.enterprise_scale:
        level = max(level, 6)
    return level


def assess_architecture(context: MissionArchitectureContext) -> Dict:
    if context.risk not in {"low", "medium", "high", "critical"}:
        raise ValueError("risk must be low, medium, high, or critical")
    if context.evidence_level not in EVIDENCE_AUTHORITY_CAP:
        raise ValueError(
            "evidence_level must be none, hypothesis, prototype, validated, or operational"
        )
    if context.requested_level is not None and context.requested_level not in ARCHITECTURES:
        raise ValueError("requested_level must be between 1 and 6")

    required = _required_level(context)
    evidence_cap = EVIDENCE_AUTHORITY_CAP[context.evidence_level]
    authorized = min(required, evidence_cap)
    missing_controls = []

    if context.consequential_actions and "human_approval" not in context.controls:
        missing_controls.append("human_approval")
    if required >= 5 and "validation" not in context.controls:
        missing_controls.append("validation")
    if required >= 5 and "recovery" not in context.controls:
        missing_controls.append("recovery")
    if required >= 6:
        for control in ("observability", "audit_log", "cost_tracking", "access_control"):
            if control not in context.controls:
                missing_controls.append(control)

    if required > evidence_cap:
        status = "evidence_blocked"
    elif missing_controls:
        status = "control_blocked"
    else:
        status = "authorized"

    request_fit = None
    if context.requested_level is not None:
        if context.requested_level < required:
            request_fit = "insufficient"
        elif context.requested_level > required:
            request_fit = "over_complex"
        else:
            request_fit = "minimum_safe"

    return {
        "status": status,
        "principle": "least_complex_safe_architecture",
        "required_level": required,
        "required_architecture": ARCHITECTURES[required],
        "evidence_level": context.evidence_level,
        "evidence_authority_cap": evidence_cap,
        "maximum_authorized_architecture": ARCHITECTURES[evidence_cap],
        "authorized_level": authorized,
        "authorized_architecture": ARCHITECTURES[authorized],
        "requested_level": context.requested_level,
        "requested_architecture": (
            ARCHITECTURES[context.requested_level]
            if context.requested_level is not None
            else None
        ),
        "requested_fit": request_fit,
        "missing_controls": missing_controls,
        "execution_authorized": status == "authorized",
        "rationale": (
            f"Mission requires level {required} ({ARCHITECTURES[required]}). "
            f"Evidence '{context.evidence_level}' authorizes through level {evidence_cap}."
        ),
    }
