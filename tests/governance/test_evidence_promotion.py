"""Evidence-strength and promotion-gate tests.

Covers mission section 19 bullets:
  - successful execution but failed promotion
"""
from governance import evidence as ev
from governance.authority import AuthorityDecision
from governance.promotion import can_promote
from governance.types import AuthorityState, EvidenceState


def _decision(state: AuthorityState, matched="P-x") -> AuthorityDecision:
    return AuthorityDecision(
        decision=state, reason="test", matched_policy={"policy_id": matched}, constraints={},
        approval_required=False, evidence=(), checked_at="now", check_id="CHECK-test",
    )


def test_evidence_starts_unknown():
    assert ev.current_evidence_state("subject:never-mentioned") == EvidenceState.UNKNOWN


def test_single_observation_is_observed_not_supported():
    ev.observe("subject:a", "first look", source="agent:1")
    assert ev.current_evidence_state("subject:a") == EvidenceState.OBSERVED


def test_two_independent_observations_escalate_to_supported():
    ev.observe("subject:b", "first look", source="agent:1")
    assert ev.current_evidence_state("subject:b") == EvidenceState.OBSERVED
    ev.observe("subject:b", "second, independent look", source="agent:2")
    assert ev.current_evidence_state("subject:b") == EvidenceState.SUPPORTED


def test_repeated_observation_from_same_source_does_not_escalate():
    ev.observe("subject:c", "look 1", source="agent:1")
    ev.observe("subject:c", "look 2 (same source)", source="agent:1")
    assert ev.current_evidence_state("subject:c") == EvidenceState.OBSERVED


def test_validate_reaches_validated():
    ev.observe("subject:d", "look", source="agent:1")
    ev.validate("subject:d", "independent re-check", validated_by="agent:2", verification_method="rerun_test_suite")
    assert ev.current_evidence_state("subject:d") == EvidenceState.VALIDATED


def test_institutionalize_reaches_top_state():
    ev.validate("subject:e", "checked", validated_by="human:owner", verification_method="manual")
    ev.institutionalize("subject:e", "adopted as baseline", decision_ref="promotion:subject:e:RELEASED")
    assert ev.current_evidence_state("subject:e") == EvidenceState.INSTITUTIONALIZED


def test_successful_execution_does_not_imply_promotion_allowed():
    """Direct test of mission section 11's example: strong evidence alone
    (even VALIDATED) does not grant promotion if authority says HUMAN_ONLY
    and the actor is an agent."""
    ev.validate("subject:f", "build+tests+device all passed", validated_by="agent:ci", verification_method="full_suite")
    evidence_state = ev.current_evidence_state("subject:f")
    assert evidence_state == EvidenceState.VALIDATED

    human_only_decision = _decision(AuthorityState.HUMAN_ONLY)
    result = can_promote(
        artifact_id="subject:f", from_state="CANDIDATE", to_state="PRODUCTION",
        evidence_state=evidence_state, authority_decision=human_only_decision, actor_kind="agent",
    )
    assert result.allowed is False
    assert "authority" in result.reason.lower()


def test_promotion_allowed_when_both_authority_and_evidence_sufficient():
    ev.validate("subject:g", "verified", validated_by="human:owner", verification_method="manual")
    evidence_state = ev.current_evidence_state("subject:g")
    allowed_decision = _decision(AuthorityState.ALLOWED)
    result = can_promote(
        artifact_id="subject:g", from_state="CANDIDATE", to_state="RELEASED",
        evidence_state=evidence_state, authority_decision=allowed_decision, actor_kind="agent",
    )
    assert result.allowed is True


def test_promotion_denied_for_weak_evidence_even_with_authority():
    weak_state = EvidenceState.OBSERVED
    allowed_decision = _decision(AuthorityState.ALLOWED)
    result = can_promote(
        artifact_id="subject:h", from_state="CANDIDATE", to_state="RELEASED",
        evidence_state=weak_state, authority_decision=allowed_decision, actor_kind="agent",
    )
    assert result.allowed is False
    assert "evidence" in result.reason.lower()


def test_human_actor_may_use_human_only_decision_to_promote():
    ev.institutionalize("subject:i", "adopted", decision_ref="ref-1")
    evidence_state = ev.current_evidence_state("subject:i")
    human_only_decision = _decision(AuthorityState.HUMAN_ONLY)
    result = can_promote(
        artifact_id="subject:i", from_state="VALIDATED", to_state="PRODUCTION",
        evidence_state=evidence_state, authority_decision=human_only_decision, actor_kind="human",
    )
    assert result.allowed is True
