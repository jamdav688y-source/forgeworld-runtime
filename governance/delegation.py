"""Delegation and self-escalation prevention.

Required invariant (mission section 15)::

    DELEGATED_AUTHORITY ⊆ DELEGATOR_AUTHORITY

except where a separately authorized governance authority performs the
grant. An agent may not grant another agent authority it does not itself
possess. Agent creation is not authority creation: creating a new agent
identity never, by itself, grants that identity anything -- every
capability the new agent will ever exercise must independently pass
evaluate_authority() the same as any other actor. This module's
functions are what a caller would use to try to *pre-seed* a new agent's
authority via delegation, and they enforce the subset invariant on that
path specifically.

Governance self-protection (mission section 16): MODIFY_GOVERNANCE and
AUTHORIZE_AGENT are HUMAN_ONLY in governance/policy_defaults.json. No
function here ever grants an agent actor the ability to change that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from governance.audit import emit
from governance.authority import AuthorityDecision
from governance.types import AuditEventFamily, AuthorityState

# Permissiveness ranking used only to compare "is X at least as permissive
# as Y" for the subset check -- not a claim that these states form a
# total order in general (HUMAN_ONLY and REQUIRES_APPROVAL are not
# "more permissive" than ALLOWED_BOUNDED in a real-world sense; they are
# simply ranked low enough here that they can never be used as the source
# of a delegation an agent performs).
_PERMISSIVENESS_RANK = {
    AuthorityState.DENIED: 0,
    AuthorityState.UNKNOWN: 0,
    AuthorityState.UNAVAILABLE: 0,
    AuthorityState.HUMAN_ONLY: 0,
    AuthorityState.REQUIRES_APPROVAL: 1,
    AuthorityState.ALLOWED_LOCAL: 2,
    AuthorityState.ALLOWED_BOUNDED: 2,
    AuthorityState.ALLOWED: 3,
}

# Capabilities for which no agent-initiated delegation is ever permitted,
# regardless of what the delegator claims to hold. These mirror
# policy_defaults.json's HUMAN_ONLY governance-tier entries and are
# enforced here too, defense-in-depth, so a bug in policy data alone
# cannot silently enable self-escalation.
GOVERNANCE_SELF_PROTECTED_CAPABILITIES = frozenset({"MODIFY_GOVERNANCE", "AUTHORIZE_AGENT"})


@dataclass(frozen=True)
class DelegationDecision:
    allowed: bool
    reason: str
    delegator_id: str
    delegate_id: str
    capability: str
    granted_decision: Optional[AuthorityState]


def _constraints_subset(delegated: dict, delegator: dict) -> tuple[bool, str]:
    for key, value in delegated.items():
        if key not in delegator:
            return False, f"constraint '{key}' not present in delegator's own constraints"
        bound = delegator[key]
        if isinstance(value, (int, float)) and isinstance(bound, (int, float)):
            if value > bound:
                return False, f"constraint '{key}'={value} exceeds delegator bound {bound}"
        elif isinstance(value, list) and isinstance(bound, list):
            if not set(value).issubset(set(bound)):
                return False, f"constraint '{key}' set {value} is not a subset of delegator's {bound}"
        elif isinstance(value, bool) and isinstance(bound, bool):
            if value and not bound:
                return False, f"constraint '{key}'=True but delegator bound is False"
        elif value != bound:
            return False, f"constraint '{key}'={value} is not permitted by delegator bound {bound}"
    return True, "constraints are a subset of delegator's own"


def delegate_authority(
    delegator_id: str,
    delegator_kind: str,
    delegator_decision: AuthorityDecision,
    delegate_id: str,
    capability: str,
    requested_decision: AuthorityState,
    requested_constraints: Optional[dict] = None,
) -> DelegationDecision:
    """Attempt to have `delegator_id` delegate `capability` to `delegate_id`
    at `requested_decision`. Enforces DELEGATED_AUTHORITY subset of
    DELEGATOR_AUTHORITY. A human delegator with an out-of-band grant is
    not modeled here -- this function only ever certifies delegation out
    of an authority the delegator can *prove* via a real AuthorityDecision
    it was itself given.
    """
    requested_constraints = requested_constraints or {}

    if capability in GOVERNANCE_SELF_PROTECTED_CAPABILITIES:
        emit(
            AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED,
            actor_id=delegator_id,
            capability=capability,
            detail={
                "delegate_id": delegate_id,
                "requested_decision": requested_decision.value,
                "reason": "governance-self-protected capability; delegation always denied",
            },
        )
        return DelegationDecision(
            allowed=False,
            reason=f"'{capability}' is governance-self-protected and can never be delegated by any actor.",
            delegator_id=delegator_id,
            delegate_id=delegate_id,
            capability=capability,
            granted_decision=None,
        )

    delegator_rank = _PERMISSIVENESS_RANK[delegator_decision.decision]
    requested_rank = _PERMISSIVENESS_RANK[requested_decision]

    if requested_rank > delegator_rank:
        emit(
            AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED,
            actor_id=delegator_id,
            capability=capability,
            detail={
                "delegate_id": delegate_id,
                "delegator_decision": delegator_decision.decision.value,
                "requested_decision": requested_decision.value,
            },
        )
        return DelegationDecision(
            allowed=False,
            reason=(
                f"Delegation denied: requested decision {requested_decision.value} "
                f"exceeds delegator's own {delegator_decision.decision.value} for '{capability}'. "
                "DELEGATED_AUTHORITY must be a subset of DELEGATOR_AUTHORITY."
            ),
            delegator_id=delegator_id,
            delegate_id=delegate_id,
            capability=capability,
            granted_decision=None,
        )

    if requested_decision == AuthorityState.ALLOWED_BOUNDED:
        ok, detail = _constraints_subset(requested_constraints, delegator_decision.constraints)
        if not ok:
            emit(
                AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED,
                actor_id=delegator_id,
                capability=capability,
                detail={"delegate_id": delegate_id, "constraint_violation": detail},
            )
            return DelegationDecision(
                allowed=False,
                reason=f"Delegation denied: {detail}",
                delegator_id=delegator_id,
                delegate_id=delegate_id,
                capability=capability,
                granted_decision=None,
            )

    return DelegationDecision(
        allowed=True,
        reason=f"'{capability}' delegated at {requested_decision.value}, within delegator's own {delegator_decision.decision.value}.",
        delegator_id=delegator_id,
        delegate_id=delegate_id,
        capability=capability,
        granted_decision=requested_decision,
    )


def guard_self_escalation(actor_id: str, actor_kind: str, capability: str, attempted_change: dict) -> DelegationDecision:
    """Call before any code path that would modify governance policy
    itself (MODIFY_GOVERNANCE) or grant/register a new agent's authority
    (AUTHORIZE_AGENT). Always denies non-human actors; always logs the
    attempt as AUTHORITY_ESCALATION_ATTEMPTED regardless of outcome, so
    even a *permitted* human change to governance leaves an audit trail.
    """
    if actor_kind != "human":
        emit(
            AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED,
            actor_id=actor_id,
            capability=capability,
            detail={"attempted_change": attempted_change, "actor_kind": actor_kind},
        )
        return DelegationDecision(
            allowed=False,
            reason=f"'{capability}' may only be performed by a human actor; actor_kind='{actor_kind}' denied.",
            delegator_id=actor_id,
            delegate_id=actor_id,
            capability=capability,
            granted_decision=None,
        )

    emit(
        AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED,
        actor_id=actor_id,
        capability=capability,
        detail={"attempted_change": attempted_change, "actor_kind": actor_kind, "note": "human-initiated; logged for audit trail, not denied on this basis alone"},
    )
    return DelegationDecision(
        allowed=True,
        reason="Human actor may modify governance policy; still requires the capability's own authority evaluation to pass.",
        delegator_id=actor_id,
        delegate_id=actor_id,
        capability=capability,
        granted_decision=AuthorityState.HUMAN_ONLY,
    )
