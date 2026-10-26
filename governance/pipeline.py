"""The canonical control sequence (mission section 3)::

    INTENT
      -> CAPABILITY CHECK
      -> AUTHORITY CHECK
      -> RISK / APPROVAL CHECK
      -> EXECUTE
      -> VERIFY
      -> EVIDENCE RECORD
      -> PROMOTION CHECK
      -> STATE TRANSITION

Any denied stage terminates or escalates cleanly, and no downstream stage
infers success because an upstream stage passed. In particular:
  - a CAPABILITY CHECK pass never implies AUTHORITY,
  - an AUTHORITY CHECK pass never implies the action was already executed,
  - EXECUTION succeeding never implies VERIFY was run or passed,
  - EVIDENCE existing never implies PROMOTION is allowed.

This is the module the NRM tag-push incident should have gone through:
capability_available=True (git + network both reachable), but
evaluate_authority(PUSH_TAG) = REQUIRES_APPROVAL, so the pipeline would
have halted *before* attempting the push rather than attempting it,
catching a 403, and then deciding what to do after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from governance import approval as approval_mod
from governance import evidence as evidence_mod
from governance.audit import emit
from governance.authority import AuthorityDecision, evaluate_authority
from governance.promotion import PromotionDecision, can_promote
from governance.types import AUTONOMOUS_EXECUTABLE_STATES, AuditEventFamily, AuthorityState, FailureCategory
from execution.failure_classification import classify_failure


@dataclass
class PipelineResult:
    status: str
    stage_reached: str
    actor_id: str
    capability: str
    authority_decision: Optional[AuthorityDecision] = None
    approval: Optional[approval_mod.ApprovalRequest] = None
    execution_error: Optional[str] = None
    execution_value: Any = None
    verified: Optional[bool] = None
    evidence_state: Optional[str] = None
    promotion_decision: Optional[PromotionDecision] = None
    failure_category: Optional[FailureCategory] = None
    reason: str = ""
    events: list = field(default_factory=list)


def run_pipeline(
    *,
    actor_id: str,
    actor_kind: str,
    capability: str,
    target: Optional[dict] = None,
    capability_available: bool,
    action_fn: Optional[Callable[[], Any]] = None,
    verify_fn: Optional[Callable[[Any], bool]] = None,
    context: Optional[dict] = None,
    evidence_subject: Optional[str] = None,
    promote_to: Optional[str] = None,
    from_state: str = "UNKNOWN",
    required_evidence_state=None,
    risk: str = "MEDIUM",
    approval_reason: str = "",
    approval_proposed_action: str = "",
) -> PipelineResult:
    target = target or {}
    context = context or {}
    evidence_subject = evidence_subject or f"{capability}:{target}"
    events: list = []

    # ---- STAGE 1: INTENT ---------------------------------------------
    events.append(emit(AuditEventFamily.AUTHORITY_CHECKED, actor_id, capability, {"stage": "INTENT", "target": target}))

    # ---- STAGE 2: CAPABILITY CHECK -------------------------------------
    if not capability_available:
        events.append(emit(AuditEventFamily.EXECUTION_FAILED, actor_id, capability, {"stage": "CAPABILITY_CHECK", "reason": "capability unavailable"}))
        return PipelineResult(
            status="CAPABILITY_MISSING",
            stage_reached="CAPABILITY_CHECK",
            actor_id=actor_id,
            capability=capability,
            failure_category=FailureCategory.CAPABILITY_MISSING,
            reason="Capability is not reachable; authority was never evaluated because there is nothing to authorize the use of.",
            events=events,
        )

    # ---- STAGE 3: AUTHORITY CHECK ---------------------------------------
    decision = evaluate_authority(actor_id=actor_id, capability=capability, target=target, context=context)
    events.append(emit(AuditEventFamily.AUTHORITY_CHECKED, actor_id, capability, {"stage": "AUTHORITY_CHECK", "decision": decision.decision.value, "reason": decision.reason}))

    if decision.decision == AuthorityState.DENIED:
        events.append(emit(AuditEventFamily.AUTHORITY_DENIED, actor_id, capability, {"reason": decision.reason}))
        return PipelineResult(
            status="AUTHORITY_DENIED", stage_reached="AUTHORITY_CHECK", actor_id=actor_id, capability=capability,
            authority_decision=decision, failure_category=FailureCategory.AUTHORITY_DENIED, reason=decision.reason, events=events,
        )

    if decision.decision == AuthorityState.UNKNOWN:
        events.append(emit(AuditEventFamily.AUTHORITY_DENIED, actor_id, capability, {"reason": decision.reason, "note": "UNKNOWN never defaults to ALLOWED"}))
        return PipelineResult(
            status="AUTHORITY_UNKNOWN", stage_reached="AUTHORITY_CHECK", actor_id=actor_id, capability=capability,
            authority_decision=decision, failure_category=FailureCategory.AUTHORITY_UNKNOWN, reason=decision.reason, events=events,
        )

    if decision.decision == AuthorityState.UNAVAILABLE:
        return PipelineResult(
            status="AUTHORITY_UNAVAILABLE", stage_reached="AUTHORITY_CHECK", actor_id=actor_id, capability=capability,
            authority_decision=decision, reason=decision.reason, events=events,
        )

    if decision.decision == AuthorityState.HUMAN_ONLY and actor_kind != "human":
        events.append(emit(AuditEventFamily.AUTHORITY_DENIED, actor_id, capability, {"reason": "HUMAN_ONLY capability attempted by non-human actor"}))
        return PipelineResult(
            status="HUMAN_ONLY_DENIED", stage_reached="AUTHORITY_CHECK", actor_id=actor_id, capability=capability,
            authority_decision=decision, failure_category=FailureCategory.AUTHORITY_DENIED,
            reason=f"'{capability}' is HUMAN_ONLY; no autonomous agent may perform it.", events=events,
        )

    # ---- STAGE 4: RISK / APPROVAL CHECK ---------------------------------
    if decision.decision == AuthorityState.REQUIRES_APPROVAL:
        existing = approval_mod.find_active_approval(capability, target, actor_id)
        if existing is None:
            req = approval_mod.request_approval(
                requested_by=actor_id,
                capability=capability,
                target=target,
                reason=approval_reason or decision.reason,
                risk=risk,
                proposed_action=approval_proposed_action or f"execute {capability} against {target}",
                evidence_summary=list(decision.evidence),
            )
            events.append(emit(AuditEventFamily.APPROVAL_REQUESTED, actor_id, capability, {"approval_id": req.approval_id}))
            return PipelineResult(
                status="AWAITING_APPROVAL", stage_reached="APPROVAL_CHECK", actor_id=actor_id, capability=capability,
                authority_decision=decision, approval=req, failure_category=FailureCategory.APPROVAL_REQUIRED,
                reason=f"Approval '{req.approval_id}' created and PENDING; execution halted until a human decides it.",
                events=events,
            )
        if existing.status.value != "APPROVED":
            return PipelineResult(
                status="AWAITING_APPROVAL", stage_reached="APPROVAL_CHECK", actor_id=actor_id, capability=capability,
                authority_decision=decision, approval=existing, failure_category=FailureCategory.APPROVAL_REQUIRED,
                reason=f"Approval '{existing.approval_id}' is {existing.status.value}, not APPROVED; execution halted.",
                events=events,
            )
        # APPROVED and not yet executed -> proceed to execute, consume it after.
        active_approval = existing
    else:
        active_approval = None
        if decision.decision not in AUTONOMOUS_EXECUTABLE_STATES and not (decision.decision == AuthorityState.HUMAN_ONLY and actor_kind == "human"):
            # Defensive catch-all for any AuthorityState not explicitly handled above.
            return PipelineResult(
                status="AUTHORITY_DENIED", stage_reached="AUTHORITY_CHECK", actor_id=actor_id, capability=capability,
                authority_decision=decision, failure_category=FailureCategory.AUTHORITY_DENIED,
                reason=f"Unhandled non-executable authority state {decision.decision.value}.", events=events,
            )

    if action_fn is None:
        return PipelineResult(
            status="AUTHORIZED_NO_ACTION", stage_reached="APPROVAL_CHECK", actor_id=actor_id, capability=capability,
            authority_decision=decision, approval=active_approval,
            reason="Authority (and approval, if required) granted; no action_fn supplied so nothing was executed.",
            events=events,
        )

    # ---- STAGE 5: EXECUTE -------------------------------------------------
    events.append(emit(AuditEventFamily.EXECUTION_STARTED, actor_id, capability, {"target": target}))
    try:
        result = action_fn()
    except Exception as exc:  # noqa: BLE001 - deliberately broad: this boundary must classify anything
        stderr_text = str(exc)
        category = classify_failure(stderr_text=stderr_text)
        events.append(emit(AuditEventFamily.EXECUTION_FAILED, actor_id, capability, {"error": stderr_text, "failure_category": category.value}))
        evidence_mod.observe(evidence_subject, f"execution failed: {stderr_text}", source=actor_id)
        events.append(emit(AuditEventFamily.EVIDENCE_RECORDED, actor_id, capability, {"subject": evidence_subject, "state": "OBSERVED"}))
        return PipelineResult(
            status="EXECUTION_FAILED", stage_reached="EXECUTE", actor_id=actor_id, capability=capability,
            authority_decision=decision, approval=active_approval, execution_error=stderr_text,
            failure_category=category, evidence_state="OBSERVED",
            reason=f"Execution raised: {stderr_text}", events=events,
        )

    events.append(emit(AuditEventFamily.EXECUTION_SUCCEEDED, actor_id, capability, {"target": target}))

    if active_approval is not None:
        approval_mod.mark_executed(active_approval.approval_id)

    # ---- STAGE 6: VERIFY ---------------------------------------------------
    verified: Optional[bool] = None
    if verify_fn is not None:
        try:
            verified = bool(verify_fn(result))
        except Exception as exc:  # noqa: BLE001
            verified = False
            events.append(emit(AuditEventFamily.EXECUTION_FAILED, actor_id, capability, {"stage": "VERIFY", "error": str(exc)}))

    # ---- STAGE 7: EVIDENCE RECORD -------------------------------------------
    if verify_fn is None:
        record = evidence_mod.observe(evidence_subject, f"execution succeeded (unverified): {result!r}", source=actor_id)
    elif verified:
        record = evidence_mod.validate(evidence_subject, f"execution succeeded: {result!r}", validated_by=actor_id, verification_method=getattr(verify_fn, "__name__", "verify_fn"))
    else:
        record = evidence_mod.observe(evidence_subject, f"execution succeeded but verification failed: {result!r}", source=actor_id)
    events.append(emit(AuditEventFamily.EVIDENCE_RECORDED, actor_id, capability, {"subject": evidence_subject, "state": record.state.value}))

    evidence_state = evidence_mod.current_evidence_state(evidence_subject)

    if promote_to is None:
        return PipelineResult(
            status="EXECUTED_SUCCESS", stage_reached="EVIDENCE_RECORD", actor_id=actor_id, capability=capability,
            authority_decision=decision, approval=active_approval, execution_value=result, verified=verified,
            evidence_state=evidence_state.value,
            reason="Executed and evidence recorded. No promotion was requested, so none occurred.",
            events=events,
        )

    # ---- STAGE 8: PROMOTION CHECK -------------------------------------------
    events.append(emit(AuditEventFamily.PROMOTION_REQUESTED, actor_id, capability, {"to_state": promote_to}))
    promotion_decision = can_promote(
        artifact_id=evidence_subject,
        from_state=from_state,
        to_state=promote_to,
        evidence_state=evidence_state,
        authority_decision=decision,
        actor_kind=actor_kind,
        required_evidence_state=required_evidence_state,
        risk=risk,
    )

    if not promotion_decision.allowed:
        events.append(emit(AuditEventFamily.PROMOTION_DENIED, actor_id, capability, {"reason": promotion_decision.reason}))
        return PipelineResult(
            status="PROMOTION_DENIED", stage_reached="PROMOTION_CHECK", actor_id=actor_id, capability=capability,
            authority_decision=decision, approval=active_approval, execution_value=result, verified=verified,
            evidence_state=evidence_state.value, promotion_decision=promotion_decision,
            failure_category=FailureCategory.PROMOTION_DENIED, reason=promotion_decision.reason, events=events,
        )

    # ---- STAGE 9: STATE TRANSITION -------------------------------------------
    events.append(emit(AuditEventFamily.PROMOTION_GRANTED, actor_id, capability, {"to_state": promote_to}))
    evidence_mod.institutionalize(evidence_subject, f"promoted {from_state} -> {promote_to}", decision_ref=f"promotion:{evidence_subject}:{promote_to}")

    return PipelineResult(
        status="PROMOTED", stage_reached="STATE_TRANSITION", actor_id=actor_id, capability=capability,
        authority_decision=decision, approval=active_approval, execution_value=result, verified=verified,
        evidence_state=evidence_mod.current_evidence_state(evidence_subject).value, promotion_decision=promotion_decision,
        reason=promotion_decision.reason, events=events,
    )
