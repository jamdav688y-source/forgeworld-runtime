"""NRM tag-push incident regression fixture (mission section 18).

Real incident this reproduces: in this same working session, prior to
this governance layer existing, `git push origin NRM-v0.1-CLASSROOM`
returned:

    error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403
    send-pack: unexpected disconnect while reading sideband packet
    fatal: the remote end hung up unexpectedly

immediately after `git push -u origin claude/next-right-move-pwa-t0h6p5`
(a branch push) succeeded with the same session credentials. See
docs/evidence/NRM_TAG_403_CASE.md for the full case writeup.

Scenario modeled here, per the mission's exact framing:
  "Actor can push branch. Actor attempts PUSH_TAG. Remote returns HTTP 403."

`test_nrm_incident_full_regression` runs the whole scenario as ONE
sequence sharing one audit/evidence/approval trail (this file's test
isolation fixture gives every *test function* its own fresh storage, so
splitting this into many small functions would make several assertions
pass vacuously against empty logs instead of actually proving anything
about this scenario -- see the single big test below for why it is one
function). The ten numbered comments below map 1:1 to mission section
18's ten expected-behavior items.
"""
from governance import approval as ap
from governance import audit
from governance import evidence as ev
from governance.authority import evaluate_authority
from governance.pipeline import run_pipeline
from governance.types import AuditEventFamily, AuthorityState, FailureCategory
from execution.failure_classification import classify_failure, retry_policy_for

REPO_TARGET_BRANCH = {
    "resource": "repository",
    "target": "jamdav688y-source/forgeworld-runtime",
    "ref_pattern": "refs/heads/claude/next-right-move-pwa-t0h6p5",
}
REPO_TARGET_TAG = {
    "resource": "repository",
    "target": "jamdav688y-source/forgeworld-runtime",
    "ref_pattern": "refs/tags/NRM-v0.1-CLASSROOM",
}
REAL_STDERR = (
    "error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403\n"
    "send-pack: unexpected disconnect while reading sideband packet\n"
    "fatal: the remote end hung up unexpectedly"
)


def test_nrm_incident_full_regression():
    # --- setup fact matching the real incident: branch-write succeeded ---
    branch_result = run_pipeline(
        actor_id="agent:claude-code-session", actor_kind="agent", capability="WRITE_BRANCH",
        target=REPO_TARGET_BRANCH, context={"force_push": False}, capability_available=True,
        action_fn=lambda: "branch pushed: fd219f5..4d66315",
    )
    assert branch_result.status == "EXECUTED_SUCCESS"

    # --- actor attempts PUSH_TAG -----------------------------------------
    # With this governance layer in place, the pipeline now catches what
    # the historical incident could not: it halts BEFORE attempting the
    # push at all, because PUSH_TAG's policy is REQUIRES_APPROVAL.
    remote_was_called = []
    push_result = run_pipeline(
        actor_id="agent:claude-code-session", actor_kind="agent", capability="PUSH_TAG",
        target=REPO_TARGET_TAG, capability_available=True,
        action_fn=lambda: remote_was_called.append(True),
        approval_reason="Freeze validated NRM v0.1 classroom baseline",
        approval_proposed_action="git push origin NRM-v0.1-CLASSROOM",
    )

    # 1. System records execution attempt (as an APPROVAL_REQUESTED audit
    #    event, not a silently dropped intent).
    events = audit.read_events()
    assert any(e["family"] == AuditEventFamily.APPROVAL_REQUESTED.value and e["capability"] == "PUSH_TAG" for e in events)

    assert push_result.status == "AWAITING_APPROVAL"
    assert remote_was_called == []  # the blind attempt itself never happened
    assert push_result.approval is not None
    assert push_result.approval.status.value == "PENDING"

    # 7. Approval/escalation path is generated.
    pending = ap.get_current_state(push_result.approval.approval_id)
    assert pending is not None
    # 8. Human-readable explanation is available.
    assert pending.reason
    assert push_result.reason

    # --- 4. local tag remains intact -------------------------------------
    # CREATE_TAG is ALLOWED_LOCAL and never touches the remote, so it is
    # entirely independent of PUSH_TAG's approval status.
    local_tag_result = run_pipeline(
        actor_id="agent:claude-code-session", actor_kind="agent", capability="CREATE_TAG",
        target=REPO_TARGET_TAG, capability_available=True,
        action_fn=lambda: "local tag object created: 95de3ac",
    )
    assert local_tag_result.status == "EXECUTED_SUCCESS"
    assert local_tag_result.execution_value == "local tag object created: 95de3ac"

    # --- historical replay: what actually happened before this layer existed ---
    # Even attempted directly (bypassing the now-existing pre-check), the
    # raw 403 must classify correctly and never register as success.
    # 2. Failure is classified as authorization-related.
    category = classify_failure(stderr_text=REAL_STDERR)
    assert category == FailureCategory.AUTHORITY_DENIED
    assert category != FailureCategory.NETWORK_TRANSIENT

    # 3. Retry occurs only within policy-defined bound (zero, for AUTHORITY_DENIED --
    #    matching what actually happened: 3 manual attempts, then correctly
    #    escalating rather than retrying forever).
    retry = retry_policy_for(FailureCategory.AUTHORITY_DENIED)
    assert retry.retryable is False
    assert retry.max_attempts == 0

    def push_and_fail():
        raise RuntimeError(REAL_STDERR)

    replay_result = run_pipeline(
        actor_id="agent:claude-code-session", actor_kind="agent", capability="WRITE_BRANCH",
        target={**REPO_TARGET_BRANCH, "ref_pattern": "refs/heads/claude/hypothetical-replay"},
        context={"force_push": False}, capability_available=True,
        action_fn=push_and_fail, evidence_subject="nrm-tag-push-replay",
    )
    # 5. No success event is emitted for the failed attempt.
    assert replay_result.status == "EXECUTION_FAILED"
    assert replay_result.failure_category == FailureCategory.AUTHORITY_DENIED
    events = audit.read_events()
    assert not any(
        e["family"] == AuditEventFamily.EXECUTION_SUCCEEDED.value and e["detail"].get("target", {}).get("ref_pattern") == "refs/heads/claude/hypothetical-replay"
        for e in events
    )
    assert ev.current_evidence_state("nrm-tag-push-replay") == ev.EvidenceState.OBSERVED  # not VALIDATED/INSTITUTIONALIZED

    # --- 6. no release promotion occurs -----------------------------------
    # Nothing in this whole scenario ever requested a promotion, so there
    # must be zero PROMOTION_GRANTED events anywhere in this run's trail.
    events = audit.read_events()
    assert not any(e["family"] == AuditEventFamily.PROMOTION_GRANTED.value for e in events)

    # --- 9. branch-write authority is NOT revoked merely because PUSH_TAG failed ---
    branch_decision_after = evaluate_authority(
        actor_id="agent:claude-code-session", capability="WRITE_BRANCH",
        target=REPO_TARGET_BRANCH, context={"force_push": False},
    )
    assert branch_decision_after.decision == AuthorityState.ALLOWED_BOUNDED

    # --- 10. PUSH_TAG failure does not imply global repository failure ----
    # Other, unrelated capabilities against the same repository are unaffected.
    unrelated_decision = evaluate_authority(
        actor_id="agent:claude-code-session", capability="CREATE_TAG", target=REPO_TARGET_TAG,
    )
    assert unrelated_decision.decision == AuthorityState.ALLOWED_LOCAL

    # --- happy path: a human actually grants the approval -----------------
    ap.decide_approval(
        push_result.approval.approval_id, ap.ApprovalStatus.APPROVED,
        decided_by="human:jamdav688y", decider_kind="human", reason="reviewed and approved",
    )
    pushed = []
    second = run_pipeline(
        actor_id="agent:claude-code-session", actor_kind="agent", capability="PUSH_TAG",
        target=REPO_TARGET_TAG, capability_available=True,
        action_fn=lambda: pushed.append("pushed") or "remote tag published",
    )
    assert second.status == "EXECUTED_SUCCESS"
    assert pushed == ["pushed"]

    # Approval is single-use (mission section 9): a further attempt needs a fresh one.
    third = run_pipeline(
        actor_id="agent:claude-code-session", actor_kind="agent", capability="PUSH_TAG",
        target=REPO_TARGET_TAG, capability_available=True, action_fn=lambda: "should not run",
    )
    assert third.status == "AWAITING_APPROVAL"
    assert third.approval.approval_id != push_result.approval.approval_id
