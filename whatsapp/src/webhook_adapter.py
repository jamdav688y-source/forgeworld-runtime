"""Inbound webhook intake: authenticity, idempotency, per-event isolation.

Verification method confirmed live against Meta's Graph API webhooks docs
during this session (see governance/01_PLATFORM_POLICY_EVIDENCE.md):
HMAC-SHA256 over the raw request body, keyed with the app secret, compared
against the `X-Hub-Signature-256` header.
"""
import hashlib
import hmac
import json
import os
import time
import traceback
import uuid

from . import ledger, normalize


class VerificationError(Exception):
    pass


def verify_challenge(query: dict) -> str:
    """GET handshake: hub.mode=subscribe, hub.verify_token, hub.challenge."""
    configured_token = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if not configured_token:
        raise VerificationError("WHATSAPP_VERIFY_TOKEN is not configured")
    if query.get("hub.mode") != "subscribe":
        raise VerificationError("hub.mode must be 'subscribe'")
    if not hmac.compare_digest(query.get("hub.verify_token", ""), configured_token):
        raise VerificationError("hub.verify_token mismatch")
    return query.get("hub.challenge", "")


def verify_signature(raw_body: bytes, signature_header: str, app_secret: str = None) -> bool:
    app_secret = app_secret if app_secret is not None else os.environ.get("WHATSAPP_APP_SECRET")
    if not app_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    provided = signature_header[len("sha256="):]
    computed = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, computed)


def is_duplicate(platform_message_id: str) -> bool:
    if not platform_message_id:
        return False
    return ledger.exists_by(ledger.CONVERSATION_LEDGER, platform_message_id=platform_message_id)


def process_webhook_payload(raw_body: bytes, signature_header: str) -> dict:
    """Full inbound path for one webhook delivery. Returns a processing
    result; never raises for per-event problems -- one bad event must not
    block the rest of the batch (mission Section 7.11).
    """
    trace_id = str(uuid.uuid4())
    raw_payload_hash = hashlib.sha256(raw_body).hexdigest()

    webhook_verified = verify_signature(raw_body, signature_header)
    if not webhook_verified:
        record = {
            "trace_id": trace_id,
            "state": "BLOCKED_BY_POLICY",
            "reason": "invalid or missing X-Hub-Signature-256",
            "raw_payload_hash": raw_payload_hash,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        ledger.append(ledger.EXECUTION_LEDGER, record)
        return {"status": "BLOCKED_BY_POLICY", "trace_id": trace_id, "events": []}

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        record = {
            "trace_id": trace_id,
            "state": "REVISION_REQUIRED",
            "reason": f"malformed JSON: {e}",
            "raw_payload_hash": raw_payload_hash,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        ledger.append(ledger.EXECUTION_LEDGER, record)
        return {"status": "REVISION_REQUIRED", "trace_id": trace_id, "events": []}

    try:
        raw_items = list(normalize.iter_raw_items(payload))
    except Exception as e:
        record = {
            "trace_id": trace_id,
            "state": "REVISION_REQUIRED",
            "reason": f"envelope walk failed: {e}",
            "traceback": traceback.format_exc(limit=5),
            "raw_payload_hash": raw_payload_hash,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        ledger.append(ledger.EXECUTION_LEDGER, record)
        return {"status": "REVISION_REQUIRED", "trace_id": trace_id, "events": []}

    accepted, duplicates, failed = [], [], []
    for kind, raw_item, metadata, contact_phone in raw_items:
        try:
            if kind == "message":
                event = normalize.normalize_message(
                    raw_item, metadata, contact_phone, raw_payload_hash, webhook_verified, trace_id
                )
            else:
                event = normalize.normalize_status(
                    raw_item, metadata, raw_payload_hash, webhook_verified, trace_id
                )
        except Exception as e:
            # Isolate this item's failure -- do not let it block the rest of the batch.
            failed.append({"raw_id": raw_item.get("id"), "error": str(e)})
            ledger.append(ledger.EXECUTION_LEDGER, {
                "trace_id": trace_id,
                "state": "REVISION_REQUIRED",
                "reason": f"normalization failed for {kind} id={raw_item.get('id')}: {e}",
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            continue

        try:
            if is_duplicate(event["platform_message_id"]):
                duplicates.append(event["platform_message_id"])
                continue
            ledger.append(ledger.CONVERSATION_LEDGER, event)
            accepted.append(event)
        except Exception as e:
            failed.append({"event_id": event.get("event_id"), "error": str(e)})
            ledger.append(ledger.EXECUTION_LEDGER, {
                "trace_id": trace_id,
                "state": "REVISION_REQUIRED",
                "reason": f"ledger write failed for event {event.get('event_id')}: {e}",
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            continue  # one bad event must not block the next

    status = "SAFE_AUTOMATION_EXECUTED" if accepted or duplicates else "REVISION_REQUIRED"
    return {
        "status": status,
        "trace_id": trace_id,
        "events": accepted,
        "duplicates": duplicates,
        "failed": failed,
    }
