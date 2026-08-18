"""Delivery-status reconciliation: matches inbound `statuses[]` webhook
events (sent/delivered/read/failed/deleted) back to the execution-ledger
entry for the outbound message that caused them.
"""
import time

from . import ledger

STATUS_TO_STATE = {
    "sent": "SAFE_AUTOMATION_EXECUTED",
    "delivered": "VALIDATED_COMPLETE",
    "read": "VALIDATED_COMPLETE",
    "failed": "REVISION_REQUIRED",
    "deleted": "VALIDATED_COMPLETE",
}


def apply_status_event(status_event: dict) -> dict:
    """status_event is a canonical event with message_type='status' and
    content_reference holding the raw status string (sent/delivered/...).
    """
    platform_message_id = status_event.get("platform_message_id")
    raw_status = status_event.get("content_reference", "unknown")
    matches = ledger.find(ledger.EXECUTION_LEDGER, platform_message_id=platform_message_id)

    record = {
        "platform_message_id": platform_message_id,
        "raw_status": raw_status,
        "state": STATUS_TO_STATE.get(raw_status, "REVISION_REQUIRED"),
        "matched_send_record": bool(matches),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    ledger.append(ledger.EXECUTION_LEDGER, record)
    return record
