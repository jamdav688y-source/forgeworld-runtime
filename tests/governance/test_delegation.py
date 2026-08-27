"""Delegation and self-escalation-guard tests.

Covers mission section 19 bullets:
  - delegation within authority
  - delegation exceeding authority
  - self-escalation attempt
"""
from governance import audit
from governance.authority import AuthorityDecision
from governance.delegation import delegate_authority, guard_self_escalation
from governance.types import AuditEventFamily, AuthorityState


def _decision(state: AuthorityState, constraints=None) -> AuthorityDecision:
    return AuthorityDecision(
        decision=state, reason="test", matched_policy={"policy_id": "P-x"}, constraints=constraints or {},
        approval_required=False, evidence=(), checked_at="now", check_id="CHECK-test",
    )


def test_delegation_within_authority_is_allowed():
    delegator_decision = _decision(AuthorityState.ALLOWED_BOUNDED, constraints={"max_amount": 100})
    result = delegate_authority(
        delegator_id="agent:manager", delegator_kind="agent", delegator_decision=delegator_decision,
        delegate_id="agent:worker", capability="SPEND_FUNDS",
        requested_decision=AuthorityState.ALLOWED_BOUNDED, requested_constraints={"max_amount": 50},
    )
    assert result.allowed is True
    assert result.granted_decision == AuthorityState.ALLOWED_BOUNDED


def test_delegation_exceeding_authority_rank_is_denied():
    """Delegator only has REQUIRES_APPROVAL; cannot delegate a fully
    autonomous ALLOWED to someone else."""
    delegator_decision = _decision(AuthorityState.REQUIRES_APPROVAL)
    result = delegate_authority(
        delegator_id="agent:a", delegator_kind="agent", delegator_decision=delegator_decision,
        delegate_id="agent:b", capability="DEPLOY", requested_decision=AuthorityState.ALLOWED,
    )
    assert result.allowed is False
    assert "exceeds" in result.reason.lower()


def test_delegation_exceeding_bounded_constraints_is_denied():
    """Same decision tier (ALLOWED_BOUNDED) but a wider constraint --
    DELEGATED_AUTHORITY must be a subset, constraint by constraint too."""
    delegator_decision = _decision(AuthorityState.ALLOWED_BOUNDED, constraints={"max_amount": 50})
    result = delegate_authority(
        delegator_id="agent:manager", delegator_kind="agent", delegator_decision=delegator_decision,
        delegate_id="agent:worker", capability="SPEND_FUNDS",
        requested_decision=AuthorityState.ALLOWED_BOUNDED, requested_constraints={"max_amount": 500},
    )
    assert result.allowed is False
    assert "exceeds delegator bound" in result.reason


def test_agent_cannot_delegate_authority_it_does_not_have():
    """Agent A lacks DEPLOY authority (UNKNOWN); creating/delegating to
    agent B must not grant B deploy authority anyway."""
    delegator_decision = _decision(AuthorityState.UNKNOWN)
    result = delegate_authority(
        delegator_id="agent:a", delegator_kind="agent", delegator_decision=delegator_decision,
        delegate_id="agent:b", capability="DEPLOY", requested_decision=AuthorityState.ALLOWED,
    )
    assert result.allowed is False


def test_governance_capabilities_can_never_be_delegated_by_anyone():
    strong_decision = _decision(AuthorityState.ALLOWED)  # even a maximally-permissive delegator...
    result = delegate_authority(
        delegator_id="agent:root-ish", delegator_kind="agent", delegator_decision=strong_decision,
        delegate_id="agent:new", capability="MODIFY_GOVERNANCE", requested_decision=AuthorityState.ALLOWED,
    )
    assert result.allowed is False
    assert "governance-self-protected" in result.reason.lower() or "self-protected" in result.reason.lower()


def test_self_escalation_attempt_by_agent_is_denied_and_logged():
    result = guard_self_escalation(
        actor_id="agent:sneaky", actor_kind="agent", capability="MODIFY_GOVERNANCE",
        attempted_change={"capability": "PUSH_TAG", "new_decision": "ALLOWED"},
    )
    assert result.allowed is False

    events = audit.read_events()
    escalation_events = [e for e in events if e["family"] == AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED.value]
    assert len(escalation_events) == 1
    assert escalation_events[0]["actor_id"] == "agent:sneaky"


def test_self_escalation_by_human_is_permitted_but_still_audited():
    result = guard_self_escalation(
        actor_id="human:jamdav688y", actor_kind="human", capability="MODIFY_GOVERNANCE",
        attempted_change={"capability": "PUSH_TAG", "new_decision": "ALLOWED"},
    )
    assert result.allowed is True

    events = audit.read_events()
    escalation_events = [e for e in events if e["family"] == AuditEventFamily.AUTHORITY_ESCALATION_ATTEMPTED.value]
    assert len(escalation_events) == 1  # still logged even though permitted
    assert escalation_events[0]["actor_id"] == "human:jamdav688y"


def test_agent_creating_agent_does_not_transitively_grant_authority():
    """Agent creation is not authority creation: AUTHORIZE_AGENT itself
    is governance-self-protected, so no agent can grant a new agent
    identity anything through this path."""
    strong_decision = _decision(AuthorityState.ALLOWED)
    result = delegate_authority(
        delegator_id="agent:creator", delegator_kind="agent", delegator_decision=strong_decision,
        delegate_id="agent:newly-created", capability="AUTHORIZE_AGENT", requested_decision=AuthorityState.ALLOWED,
    )
    assert result.allowed is False
