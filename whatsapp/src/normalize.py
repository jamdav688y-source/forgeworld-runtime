"""Raw Meta Cloud API webhook payload -> canonical conversation event(s).

Source shapes verified against developers.facebook.com/docs/whatsapp/cloud-api
during this session (see governance/01_PLATFORM_POLICY_EVIDENCE.md). Unknown
or unhandled message types degrade to message_type="unknown" rather than
guessing structure -- never treat an unrecognized shape as a specific type.
"""
import hashlib
import hmac
import os
import time
import uuid

from . import schema

KNOWN_TEXT_LIKE = {"text"}
KNOWN_MEDIA = {"audio", "image", "video", "document", "sticker"}
KNOWN_OTHER = {"interactive", "location", "contacts"}


class ConfigurationError(Exception):
    pass


def hash_phone(phone: str, salt: str = None) -> str:
    """Pseudonymize a raw phone number. No hardcoded fallback salt: a
    silent default would ship in this public repo's source, giving zero
    real protection while looking configured. Missing salt is a loud
    failure, not a quiet weak default (mission Section 17: do not guess).
    """
    salt = salt if salt is not None else os.environ.get("WHATSAPP_ID_SALT")
    if not salt:
        raise ConfigurationError(
            "WHATSAPP_ID_SALT is not set -- refusing to derive a contact_id with no real salt"
        )
    return hmac.new(salt.encode(), phone.encode(), hashlib.sha256).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_hash_for_message(msg: dict) -> str:
    msg_type = msg.get("type", "unknown")
    if msg_type == "text":
        body = msg.get("text", {}).get("body", "")
        return sha256_hex(body.encode())
    if msg_type in KNOWN_MEDIA:
        media_id = msg.get(msg_type, {}).get("id", "")
        return sha256_hex(f"{msg_type}:{media_id}".encode())
    return sha256_hex(str(msg).encode())


def _classify_type(raw_type: str) -> str:
    if raw_type == "text":
        return "text"
    if raw_type in {"audio", "image", "video", "document"}:
        return raw_type
    if raw_type in {"interactive", "location"}:
        return raw_type
    return "unknown"


def normalize_message(
    message: dict,
    metadata: dict,
    contact_phone: str,
    raw_payload_hash: str,
    webhook_verified: bool,
    trace_id: str = None,
) -> dict:
    """One inbound `messages[]` entry -> one canonical event."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    occurred_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(message.get("timestamp", time.time())))
    )
    contact_id = hash_phone(contact_phone)
    business_number = metadata.get("display_phone_number", "unknown")
    conversation_id = hash_phone(f"{contact_phone}:{business_number}")

    return schema.new_event(
        event_id=str(uuid.uuid4()),
        direction="inbound",
        occurred_at=occurred_at,
        received_at=now,
        contact_id=contact_id,
        conversation_id=conversation_id,
        platform_message_id=message.get("id"),
        reply_to_message_id=(message.get("context") or {}).get("id"),
        message_type=_classify_type(message.get("type", "unknown")),
        content_reference=None,
        content_hash=_content_hash_for_message(message),
        consent_state="unknown",
        retention_class="operational",
        evidence_class="customer-statement",
        authority_state="observe",
        processing_trace_id=trace_id or str(uuid.uuid4()),
        provenance={
            "source": "whatsapp-cloud-api",
            "webhook_verified": webhook_verified,
            "raw_payload_hash": raw_payload_hash,
        },
    )


def normalize_status(
    status: dict,
    metadata: dict,
    raw_payload_hash: str,
    webhook_verified: bool,
    trace_id: str = None,
) -> dict:
    """One `statuses[]` entry (sent/delivered/read/failed) -> canonical event."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    occurred_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(status.get("timestamp", time.time())))
    )
    recipient = status.get("recipient_id", "unknown")
    business_number = metadata.get("display_phone_number", "unknown")
    contact_id = hash_phone(recipient)
    conversation_id = hash_phone(f"{recipient}:{business_number}")

    return schema.new_event(
        event_id=str(uuid.uuid4()),
        direction="outbound",
        occurred_at=occurred_at,
        received_at=now,
        contact_id=contact_id,
        conversation_id=conversation_id,
        platform_message_id=status.get("id"),
        reply_to_message_id=None,
        message_type="status",
        content_reference=status.get("status"),
        content_hash=sha256_hex(str(status).encode()),
        consent_state="not-required",
        retention_class="operational",
        evidence_class="platform-event",
        authority_state="observe",
        processing_trace_id=trace_id or str(uuid.uuid4()),
        provenance={
            "source": "whatsapp-cloud-api",
            "webhook_verified": webhook_verified,
            "raw_payload_hash": raw_payload_hash,
        },
    )


def iter_raw_items(payload: dict):
    """Walk the Meta webhook envelope and yield one ("message"|"status", raw_item,
    metadata, contact_phone) tuple per item, without normalizing yet. Kept
    separate from normalization so the caller can isolate failures per item
    (one malformed message must not block the rest of the batch).
    """
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            contacts = {c.get("wa_id"): c for c in value.get("contacts", [])}
            for message in value.get("messages", []):
                contact_phone = message.get("from") or next(iter(contacts), "unknown")
                yield "message", message, metadata, contact_phone
            for status in value.get("statuses", []):
                yield "status", status, metadata, None


def extract_events(payload: dict, raw_payload_hash: str, webhook_verified: bool, trace_id: str = None) -> list:
    """Convenience wrapper used by tests/tools that want the whole batch at
    once and are fine with an all-or-nothing result. The live webhook path
    (webhook_adapter.process_webhook_payload) uses iter_raw_items directly so
    it can isolate per-item failures instead.
    """
    events = []
    for kind, raw_item, metadata, contact_phone in iter_raw_items(payload):
        if kind == "message":
            events.append(normalize_message(raw_item, metadata, contact_phone, raw_payload_hash, webhook_verified, trace_id))
        else:
            events.append(normalize_status(raw_item, metadata, raw_payload_hash, webhook_verified, trace_id))
    return events
