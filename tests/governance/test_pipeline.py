"""End-to-end pipeline tests.

Covers mission section 19 bullets not already covered by the lower-level
module tests:
  - capability missing + authority allowed
  - human-only action attempted by agent
  - external boundary transition (WRITE_BRANCH succeeds, PUSH_TAG halts
    before ever calling the remote)
"""
from governance.pipeline import run_pipeline
from governance.types import FailureCategory


def test_capability_missing_halts_before_authority_check():
    calls = []
    result = run_pipeline(
        actor_id="agent:test", actor_kind="agent", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/x"},
        capability_available=False,
        action_fn=lambda: calls.append("executed"),
    )
    assert result.status == "CAPABILITY_MISSING"
    assert result.failure_category == FailureCategory.CAPABILITY_MISSING
    assert calls == []  # action_fn must never run
    assert result.authority_decision is None  # authority was never evaluated


def test_human_only_capability_attempted_by_agent_never_executes():
    calls = []
    result = run_pipeline(
        actor_id="agent:test", actor_kind="agent", capability="PROMOTE_RELEASE",
        target={"resource": "release", "target": "next-right-move"},
        capability_available=True,
        action_fn=lambda: calls.append("executed"),
    )
    assert result.status == "HUMAN_ONLY_DENIED"
    assert calls == []


def test_human_actor_may_perform_human_only_capability():
    calls = []
    result = run_pipeline(
        actor_id="human:jamdav688y", actor_kind="human", capability="PROMOTE_RELEASE",
        target={"resource": "release", "target": "next-right-move"},
        capability_available=True,
        action_fn=lambda: calls.append("executed") or "promoted",
    )
    assert result.status == "EXECUTED_SUCCESS"
    assert calls == ["executed"]


def test_allowed_bounded_executes_and_records_evidence():
    result = run_pipeline(
        actor_id="agent:test", actor_kind="agent", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/claude/foo"},
        context={"force_push": False},
        capability_available=True,
        action_fn=lambda: "pushed",
    )
    assert result.status == "EXECUTED_SUCCESS"
    assert result.execution_value == "pushed"
    assert result.evidence_state == "OBSERVED"


def test_unknown_authority_halts_and_never_executes():
    calls = []
    result = run_pipeline(
        actor_id="agent:test", actor_kind="agent", capability="TOTALLY_UNDEFINED_CAP",
        capability_available=True,
        action_fn=lambda: calls.append("executed"),
    )
    assert result.status == "AUTHORITY_UNKNOWN"
    assert calls == []


def test_requires_approval_creates_pending_approval_and_halts():
    """The generic version of the NRM scenario: PUSH_TAG's policy is
    REQUIRES_APPROVAL, so the pipeline must stop before ever calling the
    remote, and must produce something a human can act on."""
    calls = []
    target = {"resource": "repository", "target": "jamdav688y-source/forgeworld-runtime", "ref_pattern": "refs/tags/NRM-v0.1-CLASSROOM"}
    result = run_pipeline(
        actor_id="agent:test", actor_kind="agent", capability="PUSH_TAG", target=target,
        capability_available=True,
        action_fn=lambda: calls.append("pushed to remote"),
    )
    assert result.status == "AWAITING_APPROVAL"
    assert calls == []  # never attempted the actual push
    assert result.approval is not None
    assert result.approval.status.value == "PENDING"
    assert result.failure_category == FailureCategory.APPROVAL_REQUIRED


def test_execution_failure_is_classified_and_recorded_as_evidence_not_success():
    def boom():
        raise RuntimeError("error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403")

    result = run_pipeline(
        actor_id="agent:test", actor_kind="agent", capability="WRITE_BRANCH",
        target={"resource": "repository", "target": "any/repo", "ref_pattern": "refs/heads/claude/foo"},
        context={"force_push": False},
        capability_available=True,
        action_fn=boom,
    )
    assert result.status == "EXECUTION_FAILED"
    assert result.failure_category == FailureCategory.AUTHORITY_DENIED
    assert result.evidence_state == "OBSERVED"


def test_promotion_denied_after_successful_execution_for_agent_actor():
    """Direct pipeline-level version of mission section 11's example."""
    result = run_pipeline(
        actor_id="human:jamdav688y", actor_kind="human", capability="PROMOTE_RELEASE",
        target={"resource": "release", "target": "next-right-move"},
        capability_available=True,
        action_fn=lambda: "built+tested+validated",
        verify_fn=lambda v: True,
        promote_to="PRODUCTION",
        evidence_subject="promotion-test-subject",
    )
    # Human + HUMAN_ONLY + VALIDATED evidence (verify_fn passed) => allowed
    assert result.status == "PROMOTED"

    # Now the same evidence subject, but an agent attempting the promotion:
    result2 = run_pipeline(
        actor_id="agent:ci", actor_kind="agent", capability="PROMOTE_RELEASE",
        target={"resource": "release", "target": "next-right-move"},
        capability_available=True,
        action_fn=None,  # authority alone should already block this
        promote_to="PRODUCTION",
        evidence_subject="promotion-test-subject",
    )
    assert result2.status == "HUMAN_ONLY_DENIED"
