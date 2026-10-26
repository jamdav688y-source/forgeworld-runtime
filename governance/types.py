"""Shared typed vocabulary for the FORGEWORLD authority-separation layer.

This module exists because of one incident: `git push origin
NRM-v0.1-CLASSROOM` returned HTTP 403 immediately after a branch push
succeeded with the same credentials. The runtime had *capability*
(git + network reachability -- see capabilities/registry.json) but not
*authority* for that specific operation. Nothing in this repository
previously modeled that distinction: capabilities/discover.py measures
only reachability, and router/mission_router.py routes purely on
reachability + fit + cost. Reachability was being used, implicitly, as
permission. This module -- and authority.py, approval.py, evidence.py,
promotion.py, delegation.py, audit.py, pipeline.py alongside it -- make
that distinction explicit and enforceable:

    CAPABILITY != AUTHORITY != EVIDENCE != PROMOTION

None of these four concepts may collapse into a single boolean such as
``CAN_EXECUTE = true``. A design where ``if actor.has_tool: execute()``
is sufficient to authorize an action is exactly the anti-pattern this
layer exists to prevent.
"""
from __future__ import annotations

from enum import Enum

SCHEMA_VERSION = "1.0.0"


class AuthorityState(str, Enum):
    """Result of an authority check. Never inferred from capability alone.

    UNKNOWN must never silently degrade to ALLOWED -- see
    authority.evaluate_authority(), which returns UNKNOWN (not a
    permissive default) whenever no policy matches a requested
    capability/scope.
    """

    DENIED = "DENIED"
    ALLOWED = "ALLOWED"
    ALLOWED_LOCAL = "ALLOWED_LOCAL"
    ALLOWED_BOUNDED = "ALLOWED_BOUNDED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    HUMAN_ONLY = "HUMAN_ONLY"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


# States in which autonomous (non-human) execution may proceed without
# first obtaining a separate approval grant. Every other state -- including
# UNKNOWN -- must not execute autonomously.
AUTONOMOUS_EXECUTABLE_STATES = frozenset(
    {AuthorityState.ALLOWED, AuthorityState.ALLOWED_LOCAL, AuthorityState.ALLOWED_BOUNDED}
)


class EvidenceState(str, Enum):
    """How strongly a claim about the world is currently supported.

    Adopted rather than reinvented: governance/EVOLUTION_DIRECTIVE_v1.txt
    already encodes this staged-strength idea in prose ("No memory becomes
    reputation until multiple observations reinforce it", "No reputation
    becomes consequence until governance validates persistence") and
    governance/CONSTITUTION_v3.txt's core chain is EVENT -> EVIDENCE ->
    MEMORY -> REPUTATION -> ... -> CONSEQUENCE. No repository code
    previously gave this an executable vocabulary; this enum is that
    vocabulary, not a competing one.
    """

    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"
    SUPPORTED = "SUPPORTED"
    VALIDATED = "VALIDATED"
    INSTITUTIONALIZED = "INSTITUTIONALIZED"


# Ordering used to compare "is this evidence at least as strong as X".
EVIDENCE_STATE_ORDER = (
    EvidenceState.UNKNOWN,
    EvidenceState.OBSERVED,
    EvidenceState.SUPPORTED,
    EvidenceState.VALIDATED,
    EvidenceState.INSTITUTIONALIZED,
)


def evidence_at_least(state: EvidenceState, minimum: EvidenceState) -> bool:
    return EVIDENCE_STATE_ORDER.index(state) >= EVIDENCE_STATE_ORDER.index(minimum)


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXECUTED = "EXECUTED"


class FailureCategory(str, Enum):
    """See execution/failure_classification.py for the classifier.

    Kept here (not in execution/) because authority.py and pipeline.py
    both need to reference these categories without importing the
    execution package, avoiding a circular dependency.
    """

    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    AUTHORITY_DENIED = "AUTHORITY_DENIED"
    AUTHORITY_UNKNOWN = "AUTHORITY_UNKNOWN"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    NETWORK_TRANSIENT = "NETWORK_TRANSIENT"
    NETWORK_PERMANENT = "NETWORK_PERMANENT"
    RATE_LIMIT = "RATE_LIMIT"
    TARGET_REJECTED = "TARGET_REJECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    PROMOTION_DENIED = "PROMOTION_DENIED"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class TrustBoundary(str, Enum):
    """External trust boundaries an artifact/action may cross.

    Authority at boundary N never implies authority at boundary N+1 --
    each capability's policy declares which boundary it crosses, and
    evaluate_authority() only ever looks up the policy for the specific
    capability requested. There is no code path that widens a decision
    made for one boundary into a decision for another.
    """

    LOCAL_FILE = "LOCAL_FILE"
    GIT_COMMIT = "GIT_COMMIT"
    REMOTE_BRANCH = "REMOTE_BRANCH"
    REMOTE_TAG = "REMOTE_TAG"
    DEPLOYMENT_PLATFORM = "DEPLOYMENT_PLATFORM"
    PRODUCTION = "PRODUCTION"
    EXTERNAL_COMMUNICATION = "EXTERNAL_COMMUNICATION"
    FINANCIAL = "FINANCIAL"
    GOVERNANCE = "GOVERNANCE"


# Ordered for documentation/tests only -- NOT used to infer that clearing
# boundary N grants boundary N+1. See docs/governance/AUTHORITY_MODEL.md
# "External trust boundaries" for the worked example (LOCAL_FILE ... ->
# REMOTE_TAG in the NRM incident).
TRUST_BOUNDARY_ORDER = (
    TrustBoundary.LOCAL_FILE,
    TrustBoundary.GIT_COMMIT,
    TrustBoundary.REMOTE_BRANCH,
    TrustBoundary.REMOTE_TAG,
    TrustBoundary.DEPLOYMENT_PLATFORM,
    TrustBoundary.PRODUCTION,
)


class AuditEventFamily(str, Enum):
    AUTHORITY_CHECKED = "AUTHORITY_CHECKED"
    AUTHORITY_GRANTED = "AUTHORITY_GRANTED"
    AUTHORITY_DENIED = "AUTHORITY_DENIED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    PROMOTION_REQUESTED = "PROMOTION_REQUESTED"
    PROMOTION_GRANTED = "PROMOTION_GRANTED"
    PROMOTION_DENIED = "PROMOTION_DENIED"
    AUTHORITY_ESCALATION_ATTEMPTED = "AUTHORITY_ESCALATION_ATTEMPTED"
