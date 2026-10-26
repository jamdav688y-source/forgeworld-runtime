"""Canonical conversation-event contract (schema_version 1.0).

Validation is hand-rolled against schemas/conversation_event.schema.json
rather than depending on the `jsonschema` package, which is not available in
this environment and which the rest of the repo has no dependency-management
story for (no requirements.txt / lockfile exists).
"""
import json
import re
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = MODULE_ROOT / "schemas" / "conversation_event.schema.json"

MESSAGE_TYPES = {"text", "audio", "image", "video", "document", "interactive", "location", "status", "unknown"}
DIRECTIONS = {"inbound", "outbound"}
CONSENT_STATES = {"verified", "unknown", "revoked", "not-required"}
RETENTION_CLASSES = {"ephemeral", "operational", "contractual", "evidence"}
EVIDENCE_CLASSES = {"unverified-claim", "customer-statement", "platform-event", "validated-outcome"}
AUTHORITY_STATES = {"observe", "draft", "approved", "sent", "blocked"}

REQUIRED_FIELDS = [
    "event_id", "schema_version", "channel", "direction", "occurred_at", "received_at",
    "contact_id", "conversation_id", "message_type", "content_hash", "consent_state",
    "retention_class", "evidence_class", "authority_state", "processing_trace_id", "provenance",
]

HEX64 = re.compile(r"^[a-f0-9]{64}$")


def new_event(**kwargs) -> dict:
    """Build a canonical event dict with governed defaults, then validate it."""
    event = {
        "event_id": kwargs.pop("event_id"),
        "schema_version": "1.0",
        "channel": "whatsapp",
        "direction": kwargs.pop("direction"),
        "occurred_at": kwargs.pop("occurred_at"),
        "received_at": kwargs.pop("received_at"),
        "contact_id": kwargs.pop("contact_id"),
        "conversation_id": kwargs.pop("conversation_id"),
        "platform_message_id": kwargs.pop("platform_message_id", None),
        "reply_to_message_id": kwargs.pop("reply_to_message_id", None),
        "message_type": kwargs.pop("message_type"),
        "content_reference": kwargs.pop("content_reference", None),
        "content_hash": kwargs.pop("content_hash"),
        "consent_state": kwargs.pop("consent_state", "unknown"),
        "retention_class": kwargs.pop("retention_class", "operational"),
        "intent": kwargs.pop("intent", []),
        "signals": kwargs.pop("signals", []),
        "risk_flags": kwargs.pop("risk_flags", []),
        "evidence_class": kwargs.pop("evidence_class", "customer-statement"),
        "authority_state": kwargs.pop("authority_state", "observe"),
        "processing_trace_id": kwargs.pop("processing_trace_id"),
        "provenance": kwargs.pop("provenance"),
    }
    if kwargs:
        raise TypeError(f"Unexpected fields for canonical event: {sorted(kwargs)}")
    errors = validate(event)
    if errors:
        raise ValueError(f"Invalid canonical event: {errors}")
    return event


def validate(event: dict) -> list:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in event:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if event["schema_version"] != "1.0":
        errors.append("schema_version must be '1.0'")
    if event["channel"] != "whatsapp":
        errors.append("channel must be 'whatsapp'")
    if event["direction"] not in DIRECTIONS:
        errors.append(f"direction must be one of {DIRECTIONS}")
    if event["message_type"] not in MESSAGE_TYPES:
        errors.append(f"message_type must be one of {MESSAGE_TYPES}")
    if event["consent_state"] not in CONSENT_STATES:
        errors.append(f"consent_state must be one of {CONSENT_STATES}")
    if event["retention_class"] not in RETENTION_CLASSES:
        errors.append(f"retention_class must be one of {RETENTION_CLASSES}")
    if event["evidence_class"] not in EVIDENCE_CLASSES:
        errors.append(f"evidence_class must be one of {EVIDENCE_CLASSES}")
    if event["authority_state"] not in AUTHORITY_STATES:
        errors.append(f"authority_state must be one of {AUTHORITY_STATES}")
    if not HEX64.match(event["content_hash"] or ""):
        errors.append("content_hash must be a 64-char lowercase hex sha256 digest")

    prov = event["provenance"]
    if not isinstance(prov, dict):
        errors.append("provenance must be an object")
    else:
        if prov.get("source") != "whatsapp-cloud-api":
            errors.append("provenance.source must be 'whatsapp-cloud-api'")
        if "webhook_verified" not in prov or not isinstance(prov["webhook_verified"], bool):
            errors.append("provenance.webhook_verified must be a boolean")
        if not HEX64.match(prov.get("raw_payload_hash", "")):
            errors.append("provenance.raw_payload_hash must be a 64-char lowercase hex sha256 digest")

    return errors


def load_json_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)
