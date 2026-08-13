"""Approval-lifecycle tests.

Covers mission section 19 bullets:
  - approval granted
  - approval denied
  - approval expired
  - human-only action attempted by agent (decider side)
"""
import pytest

from governance import approval as ap
from governance.types import ApprovalStatus


def test_approval_requested_starts_pending():
    req = ap.request_approval(
        requested_by="agent:test", capability="PUSH_TAG", target={"ref": "refs/tags/v1"},
        reason="test", risk="MEDIUM", proposed_action="push tag v1",
    )
    assert req.status == ApprovalStatus.PENDING
    current = ap.get_current_state(req.approval_id)
    assert current.status == ApprovalStatus.PENDING


def test_approval_granted_by_human():
    req = ap.request_approval(
        requested_by="agent:test", capability="PUSH_TAG", target={"ref": "refs/tags/v1"},
        reason="test", risk="MEDIUM", proposed_action="push tag v1",
    )
    decided = ap.decide_approval(req.approval_id, ApprovalStatus.APPROVED, decided_by="human:jamdav688y", decider_kind="human")
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by == "human:jamdav688y"


def test_approval_denied_by_human():
    req = ap.request_approval(
        requested_by="agent:test", capability="DEPLOY", target={}, reason="test", risk="HIGH", proposed_action="deploy",
    )
    decided = ap.decide_approval(req.approval_id, ApprovalStatus.DENIED, decided_by="human:owner", decider_kind="human", reason="not ready")
    assert decided.status == ApprovalStatus.DENIED
    assert decided.decision_reason == "not ready"


def test_agent_cannot_decide_its_own_approval():
    """Human-only action (deciding an approval) attempted by an agent."""
    req = ap.request_approval(
        requested_by="agent:test", capability="PUSH_TAG", target={}, reason="test", risk="LOW", proposed_action="push",
    )
    with pytest.raises(PermissionError):
        ap.decide_approval(req.approval_id, ApprovalStatus.APPROVED, decided_by="agent:test", decider_kind="agent")
    # and the approval must still be PENDING -- the rejected attempt must not mutate state
    assert ap.get_current_state(req.approval_id).status == ApprovalStatus.PENDING


def test_approval_expires():
    # Use a negative offset (already-past timestamp) rather than a small
    # positive sleep, so this test isn't flaky around second boundaries --
    # timestamps here are second-resolution ISO 8601 strings.
    req = ap.request_approval(
        requested_by="agent:test", capability="PUSH_TAG", target={}, reason="test", risk="LOW",
        proposed_action="push", expires_in_seconds=-5,
    )
    current = ap.get_current_state(req.approval_id)
    assert ap._effective_status(current).status == ApprovalStatus.EXPIRED
    # even a human cannot approve an expired request -- decide_approval
    # requires PENDING, and _effective_status will have flipped it
    with pytest.raises(ValueError):
        ap.decide_approval(req.approval_id, ApprovalStatus.APPROVED, decided_by="human:owner", decider_kind="human")


def test_approval_is_single_use():
    """Approval to perform one action must not implicitly authorize a
    second execution."""
    req = ap.request_approval(
        requested_by="agent:test", capability="PUSH_TAG", target={"ref": "refs/tags/v1"},
        reason="test", risk="MEDIUM", proposed_action="push tag v1",
    )
    ap.decide_approval(req.approval_id, ApprovalStatus.APPROVED, decided_by="human:owner", decider_kind="human")
    executed = ap.mark_executed(req.approval_id)
    assert executed.status == ApprovalStatus.EXECUTED

    with pytest.raises(ValueError):
        ap.mark_executed(req.approval_id)  # cannot execute a second time off the same approval


def test_find_active_approval_only_matches_approved_not_executed():
    target = {"ref": "refs/tags/v1"}
    req = ap.request_approval(
        requested_by="agent:test", capability="PUSH_TAG", target=target, reason="t", risk="LOW", proposed_action="push",
    )
    assert ap.find_active_approval("PUSH_TAG", target, "agent:test") is None  # still PENDING

    ap.decide_approval(req.approval_id, ApprovalStatus.APPROVED, decided_by="human:owner", decider_kind="human")
    active = ap.find_active_approval("PUSH_TAG", target, "agent:test")
    assert active is not None and active.approval_id == req.approval_id

    ap.mark_executed(req.approval_id)
    assert ap.find_active_approval("PUSH_TAG", target, "agent:test") is None  # consumed


def test_cancel_approval():
    req = ap.request_approval(
        requested_by="agent:test", capability="DELETE_RECORD", target={}, reason="t", risk="LOW", proposed_action="delete",
    )
    cancelled = ap.cancel_approval(req.approval_id, cancelled_by="agent:test")
    assert cancelled.status == ApprovalStatus.CANCELLED
    with pytest.raises(ValueError):
        ap.decide_approval(req.approval_id, ApprovalStatus.APPROVED, decided_by="human:owner", decider_kind="human")
