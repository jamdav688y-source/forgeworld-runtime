"""Orchestrates the per-event chain after ledgering:
consent check -> stopword handling -> classify -> draft.
Kept separate from webhook_adapter so the heavy step (classification/draft)
never runs inside the webhook request/response path (mission Section 7.10).
"""
from . import classify as classify_mod
from . import consent as consent_mod
from . import draft as draft_mod
from . import reconcile


def handle_event(event: dict, raw_text: str = None, thread_context: dict = None) -> dict:
    if event["message_type"] == "status":
        reconciliation = reconcile.apply_status_event(event)
        return {"kind": "status_reconciled", "reconciliation": reconciliation}

    if event["direction"] != "inbound":
        return {"kind": "noop", "reason": "not an inbound message"}

    consent_mod.apply_stop_word_if_present(event["contact_id"], raw_text or "")
    consent = consent_mod.get_consent(event["contact_id"])

    classification = classify_mod.classify(event, raw_text, thread_context)

    if consent.get("consent_state") == "revoked":
        return {"kind": "no_draft", "reason": "BLOCKED_BY_CONSENT", "classification": classification}

    if classification["evidence_sufficiency"] == "insufficient":
        return {"kind": "no_draft", "reason": "BLOCKED_BY_EVIDENCE", "classification": classification}

    draft_obj = draft_mod.compile_draft(event, classification, thread_context)
    return {"kind": "draft_ready", "classification": classification, "draft": draft_obj}
