"""Authority-evaluator tests.

Covers mission section 19 bullets:
  - capability exists + authority allowed
  - capability exists + authority denied
  - capability exists + authority unknown
  - local-only authority attempting external action
  - bounded authority inside limit
  - bounded authority outside limit
"""
from governance.authority import AuthorityPolicy, evaluate_authority
from governance.types import AuthorityState


def test_authority_allowed_for_matching_scope():
    decision = evaluate_authority(
        actor_id="agent:test",
        capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/claude/foo"},
        context={"force_push": False},
    )
    assert decision.decision == AuthorityState.ALLOWED_BOUNDED
    assert decision.approval_required is False


def test_authority_denied_capability_explicitly_forbidden():
    policies = [
        AuthorityPolicy(
            policy_id="P-1", capability="DELETE_EVERYTHING", scope={"resource": "*"},
            decision=AuthorityState.DENIED, reason="never allowed",
        )
    ]
    decision = evaluate_authority(actor_id="agent:test", capability="DELETE_EVERYTHING", policies=policies)
    assert decision.decision == AuthorityState.DENIED


def test_authority_unknown_for_capability_with_no_policy():
    decision = evaluate_authority(actor_id="agent:test", capability="TOTALLY_UNDEFINED_CAPABILITY")
    assert decision.decision == AuthorityState.UNKNOWN
    assert "no policy" in decision.reason.lower() or "no policy" in decision.reason


def test_unknown_never_silently_becomes_allowed():
    """The mission's hardest single requirement: UNKNOWN must never
    degrade to ALLOWED, checked directly against the real policy table."""
    decision = evaluate_authority(actor_id="agent:test", capability="SOMETHING_NOBODY_DEFINED")
    assert decision.decision != AuthorityState.ALLOWED
    assert decision.decision == AuthorityState.UNKNOWN


def test_authority_unknown_for_capability_with_no_scope_match():
    policies = [
        AuthorityPolicy(
            policy_id="P-2", capability="WRITE_BRANCH",
            scope={"resource": "repository", "target": "only/this-repo"},
            decision=AuthorityState.ALLOWED,
        )
    ]
    decision = evaluate_authority(
        actor_id="agent:test", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "different/repo"},
        policies=policies,
    )
    assert decision.decision == AuthorityState.UNKNOWN


def test_local_only_authority_cannot_cross_external_boundary():
    """CREATE_TAG is ALLOWED_LOCAL -- it must never be treated as
    authorizing the external (remote) equivalent, PUSH_TAG. They are
    different capabilities with independently matched policies, so
    ALLOWED_LOCAL for one never leaks into a decision for the other."""
    tag_target = {"resource": "repository", "target": "any/repo", "ref_pattern": "refs/tags/v1"}
    create_decision = evaluate_authority(actor_id="agent:test", capability="CREATE_TAG", target=tag_target)
    push_decision = evaluate_authority(actor_id="agent:test", capability="PUSH_TAG", target=tag_target)

    assert create_decision.decision == AuthorityState.ALLOWED_LOCAL
    assert push_decision.decision == AuthorityState.REQUIRES_APPROVAL
    assert push_decision.decision != create_decision.decision


def test_bounded_authority_inside_limit():
    decision = evaluate_authority(
        actor_id="agent:test", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/claude/foo"},
        context={"force_push": False},
    )
    assert decision.decision == AuthorityState.ALLOWED_BOUNDED


def test_bounded_authority_outside_limit_is_denied():
    decision = evaluate_authority(
        actor_id="agent:test", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/main"},
        context={"force_push": True},
    )
    assert decision.decision == AuthorityState.DENIED


def test_bounded_authority_missing_context_is_unknown_not_allowed():
    """If we cannot verify a bounded constraint, the safe answer is
    UNKNOWN, never a silent ALLOWED."""
    decision = evaluate_authority(
        actor_id="agent:test", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/x"},
    )
    assert decision.decision == AuthorityState.UNKNOWN


def test_spend_funds_bounded_zero_default_blocks_any_spend():
    decision = evaluate_authority(
        actor_id="agent:test", capability="SPEND_FUNDS",
        target={"resource": "financial_account", "target": "acct-1"},
        context={"max_amount": 5, "currency": "USD"},
    )
    assert decision.decision == AuthorityState.DENIED


def test_revoked_policy_denies_even_if_rule_would_otherwise_allow():
    policies = [
        AuthorityPolicy(policy_id="P-REVOKE-ME", capability="SEND_EXTERNAL_MESSAGE", scope={}, decision=AuthorityState.ALLOWED)
    ]
    decision = evaluate_authority(
        actor_id="agent:test", capability="SEND_EXTERNAL_MESSAGE",
        policies=policies, revoked_policy_ids={"P-REVOKE-ME"},
    )
    assert decision.decision == AuthorityState.DENIED
    assert "revoked" in decision.reason.lower()


def test_human_only_capabilities_from_real_policy_table():
    resource_by_capability = {
        "PROMOTE_RELEASE": "release",
        "MODIFY_GOVERNANCE": "governance_policy",
        "AUTHORIZE_AGENT": "agent_registry",
        "CHANGE_PRODUCTION_CONFIGURATION": "production_configuration",
    }
    for capability, resource in resource_by_capability.items():
        decision = evaluate_authority(
            actor_id="agent:test", capability=capability, target={"resource": resource, "target": "any"},
        )
        assert decision.decision == AuthorityState.HUMAN_ONLY, capability


def test_decision_is_explainable():
    decision = evaluate_authority(
        actor_id="agent:test", capability="PUSH_TAG",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/tags/v1"},
    )
    d = decision.to_dict()
    assert d["reason"]
    assert d["matched_policy"] is not None
    assert d["evidence"]
    assert d["check_id"].startswith("CHECK-")
