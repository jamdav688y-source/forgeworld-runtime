"""Authority objects and the authority-check engine.

`evaluate_authority()` is the only function in this repository that is
allowed to answer "may this actor do this?". Nothing downstream may infer
authority from capability (see capabilities/discover.py, which only
answers "is this reachable?") or from a prior, unrelated authority grant.

Anti-pattern this file exists to prevent, verbatim from the mission brief::

    if actor.has_tool:
        execute()

Execution must require both capability sufficiency (checked elsewhere,
e.g. capabilities/discover.py reachability) *and* authority sufficiency
(checked here) -- see pipeline.run_pipeline() for how the two are
combined without either implying the other.
"""
from __future__ import annotations

import fnmatch
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from governance.types import SCHEMA_VERSION, AuthorityState

GOVERNANCE_DIR = Path(__file__).resolve().parent
DEFAULT_POLICY_PATH = GOVERNANCE_DIR / "policy_defaults.json"
DEFAULT_REVOCATIONS_PATH = GOVERNANCE_DIR / "revocations.json"


@dataclass(frozen=True)
class AuthorityPolicy:
    """A stored, scoped rule -- the "Authority Object" from the mission
    brief (section 6), adapted: policy fixtures are actor-agnostic
    templates (``actor_id`` filled in as ``"*"``) until matched against a
    specific request, at which point evaluate_authority() projects a
    per-actor AuthorityDecision from it. This avoids needing one stored
    row per (actor, capability) pair for every agent that might ever ask.
    """

    policy_id: str
    capability: str
    scope: dict
    decision: AuthorityState
    constraints: dict = field(default_factory=dict)
    reason: str = ""
    trust_boundary: Optional[str] = None
    evidence_required: tuple = ()
    granted_by: str = "policy"
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def to_authority_object(self, actor_id: str) -> dict:
        """Render the mission-section-6-shaped JSON object for a specific actor."""
        return {
            "authority_id": f"AUTH-{self.policy_id}-{actor_id}",
            "actor_id": actor_id,
            "capability": self.capability,
            "scope": self.scope,
            "decision": self.decision.value,
            "constraints": self.constraints,
            "granted_by": self.granted_by,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "evidence_required": list(self.evidence_required),
            "reason": self.reason,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AuthorityDecision:
    decision: AuthorityState
    reason: str
    matched_policy: Optional[dict]
    constraints: dict
    approval_required: bool
    evidence: tuple
    checked_at: str
    check_id: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision"] = self.decision.value
        d["evidence"] = list(self.evidence)
        return d


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_policies(path: Optional[Path] = None) -> list[AuthorityPolicy]:
    path = path or DEFAULT_POLICY_PATH
    with open(path) as f:
        raw = json.load(f)
    policies = []
    for p in raw["policies"]:
        policies.append(
            AuthorityPolicy(
                policy_id=p["policy_id"],
                capability=p["capability"],
                scope=p.get("scope", {}),
                decision=AuthorityState(p["decision"]),
                constraints=p.get("constraints", {}),
                reason=p.get("reason", ""),
                trust_boundary=p.get("trust_boundary"),
                evidence_required=tuple(p.get("evidence_required", [])),
                granted_by=p.get("granted_by", "policy"),
                valid_from=p.get("valid_from"),
                valid_until=p.get("valid_until"),
                schema_version=p.get("schema_version", SCHEMA_VERSION),
            )
        )
    return policies


def load_revocations(path: Optional[Path] = None) -> set:
    path = path or DEFAULT_REVOCATIONS_PATH
    if not path.exists():
        return set()
    with open(path) as f:
        data = json.load(f)
    return set(data.get("revoked_policy_ids", []))


def _scope_matches(policy_scope: dict, requested_scope: dict) -> bool:
    """A policy scope entry of "*" matches anything; otherwise glob-match."""
    for key, pattern in policy_scope.items():
        if pattern == "*":
            continue
        requested_value = requested_scope.get(key)
        if requested_value is None:
            return False
        if not fnmatch.fnmatch(str(requested_value), str(pattern)):
            return False
    return True


def _is_expired(policy: AuthorityPolicy) -> bool:
    if policy.valid_until is None:
        return False
    return _now() > policy.valid_until


def _check_bounded_constraints(policy: AuthorityPolicy, context: dict) -> tuple[bool, list]:
    """Validate ALLOWED_BOUNDED constraints against supplied context.

    Fails safe: any constraint key not present in `context` is reported
    as unverifiable rather than assumed satisfied.
    """
    unverifiable = []
    violated = []
    for key, allowed in policy.constraints.items():
        if key not in context:
            unverifiable.append(key)
            continue
        requested = context[key]
        if isinstance(allowed, bool):
            if requested != allowed and allowed is False and requested:
                violated.append(key)
        elif isinstance(allowed, (int, float)):
            if isinstance(requested, (int, float)) and requested > allowed:
                violated.append(key)
        elif isinstance(allowed, list):
            if requested not in allowed:
                violated.append(key)
        # unknown constraint shapes are treated as unverifiable, not satisfied
        else:
            unverifiable.append(key)
    return (len(violated) == 0 and len(unverifiable) == 0), (violated + [f"unverifiable:{k}" for k in unverifiable])


def evaluate_authority(
    actor_id: str,
    capability: str,
    target: Optional[dict] = None,
    context: Optional[dict] = None,
    policies: Optional[list[AuthorityPolicy]] = None,
    revoked_policy_ids: Optional[set] = None,
) -> AuthorityDecision:
    """The single authority-check entrypoint.

    Returns an explainable AuthorityDecision. Never returns ALLOWED for a
    capability with no matching policy -- returns UNKNOWN instead, per
    the mission's explicit requirement that UNKNOWN must not silently
    degrade to ALLOWED.
    """
    target = target or {}
    context = context or {}
    policies = load_policies() if policies is None else policies
    revoked = load_revocations() if revoked_policy_ids is None else revoked_policy_ids

    check_id = f"CHECK-{uuid.uuid4().hex[:12]}"
    checked_at = _now()
    evidence: list[str] = [f"policy_table_size={len(policies)}"]

    candidates = [p for p in policies if p.capability == capability]
    if not candidates:
        return AuthorityDecision(
            decision=AuthorityState.UNKNOWN,
            reason=f"No policy defines capability '{capability}'. Absence of a rule is not permission.",
            matched_policy=None,
            constraints={},
            approval_required=False,
            evidence=tuple(evidence + ["no_matching_policy"]),
            checked_at=checked_at,
            check_id=check_id,
        )

    scoped = [p for p in candidates if _scope_matches(p.scope, target)]
    if not scoped:
        return AuthorityDecision(
            decision=AuthorityState.UNKNOWN,
            reason=(
                f"Policy exists for '{capability}' but none match the requested scope {target!r}. "
                "An out-of-scope request is not implicitly denied OR allowed by a same-capability "
                "policy for a different scope -- it is UNKNOWN."
            ),
            matched_policy=None,
            constraints={},
            approval_required=False,
            evidence=tuple(evidence + ["no_scope_match"]),
            checked_at=checked_at,
            check_id=check_id,
        )

    policy = scoped[0]
    evidence.append(f"matched_policy={policy.policy_id}")

    if policy.policy_id in revoked:
        return AuthorityDecision(
            decision=AuthorityState.DENIED,
            reason=f"Policy '{policy.policy_id}' has been revoked.",
            matched_policy=policy.to_authority_object(actor_id),
            constraints=policy.constraints,
            approval_required=False,
            evidence=tuple(evidence + ["policy_revoked"]),
            checked_at=checked_at,
            check_id=check_id,
        )

    if _is_expired(policy):
        return AuthorityDecision(
            decision=AuthorityState.UNKNOWN,
            reason=f"Policy '{policy.policy_id}' expired at {policy.valid_until}; no successor policy evaluated.",
            matched_policy=policy.to_authority_object(actor_id),
            constraints=policy.constraints,
            approval_required=False,
            evidence=tuple(evidence + ["policy_expired"]),
            checked_at=checked_at,
            check_id=check_id,
        )

    decision = policy.decision

    if decision == AuthorityState.ALLOWED_BOUNDED:
        ok, detail = _check_bounded_constraints(policy, context)
        if not ok:
            return AuthorityDecision(
                decision=AuthorityState.UNKNOWN if all(d.startswith("unverifiable:") for d in detail) else AuthorityState.DENIED,
                reason=f"Bounded constraint check failed for '{policy.policy_id}': {detail}",
                matched_policy=policy.to_authority_object(actor_id),
                constraints=policy.constraints,
                approval_required=False,
                evidence=tuple(evidence + [f"bounded_check_failed:{detail}"]),
                checked_at=checked_at,
                check_id=check_id,
            )
        evidence.append("bounded_constraints_satisfied")

    approval_required = decision == AuthorityState.REQUIRES_APPROVAL

    return AuthorityDecision(
        decision=decision,
        reason=policy.reason or f"Matched policy '{policy.policy_id}'.",
        matched_policy=policy.to_authority_object(actor_id),
        constraints=policy.constraints,
        approval_required=approval_required,
        evidence=tuple(evidence),
        checked_at=checked_at,
        check_id=check_id,
    )
