"""Human approval workflow. Every function here represents a human decision
made through the phone-first CLI (mission Section 15) -- nothing in the
automated pipeline calls these on its own.
"""
import time

from . import ledger


def _pending_drafts() -> list:
    execution_records = ledger.read_all(ledger.EXECUTION_LEDGER)
    latest_by_draft = {}
    for r in execution_records:
        draft_id = r.get("draft_id")
        if draft_id:
            latest_by_draft[draft_id] = r
    return [r for r in latest_by_draft.values() if r["state"] == "READY_FOR_HUMAN_APPROVAL"]


def list_pending() -> list:
    return _pending_drafts()


def _decide(draft_id: str, decision_state: str, actor: str, note: str = "", **extra) -> dict:
    matches = ledger.find(ledger.EXECUTION_LEDGER, draft_id=draft_id)
    if not matches:
        raise ValueError(f"no execution ledger entry for draft_id {draft_id}")
    original = matches[-1]
    record = {
        "trace_id": original.get("trace_id"),
        "draft_id": draft_id,
        "event_id": original.get("event_id"),
        "action": original.get("action"),
        "state": decision_state,
        "authority_state": "approved" if decision_state == "APPROVED_AWAITING_SEND" else original.get("authority_state", "draft"),
        "decided_by": actor,
        "note": note,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **extra,
    }
    ledger.append(ledger.EXECUTION_LEDGER, record)
    return record


def approve(draft_id: str, actor: str, note: str = "") -> dict:
    # "APPROVED_AWAITING_SEND" is a pipeline-internal state distinct from the
    # mission's fixed terminal-state vocabulary (Section 17) -- the terminal
    # state (SAFE_AUTOMATION_EXECUTED / BLOCKED_BY_* / VALIDATED_COMPLETE) is
    # only known after outbound.send() actually runs.
    return _decide(draft_id, "APPROVED_AWAITING_SEND", actor, note)


def reject(draft_id: str, actor: str, note: str = "") -> dict:
    return _decide(draft_id, "REVISION_REQUIRED", actor, note)


def escalate(draft_id: str, actor: str, note: str = "") -> dict:
    return _decide(draft_id, "BLOCKED_BY_AUTHORITY", actor, note or "escalated to person")


def request_more_evidence(draft_id: str, actor: str, note: str = "") -> dict:
    return _decide(draft_id, "BLOCKED_BY_EVIDENCE", actor, note)


def mark_not_opportunity(draft_id: str, actor: str, note: str = "") -> dict:
    return _decide(draft_id, "VALIDATED_COMPLETE", actor, note or "not an opportunity")


def schedule_follow_up(draft_id: str, actor: str, follow_up_at: str, note: str = "") -> dict:
    return _decide(draft_id, "REVISION_REQUIRED", actor, note or f"follow up at {follow_up_at}", follow_up_at=follow_up_at)
