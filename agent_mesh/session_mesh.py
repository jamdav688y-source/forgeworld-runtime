"""Governed envelopes for Claude Code cross-session transport.

The vendor transport only moves plain text.  This module adds ForgeWorld
identity, authority, lineage, expiry, deduplication and lifecycle semantics
without pretending that receipt authorizes execution.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from uuid import uuid4


class InboundDisposition(str, Enum):
    ACCEPT_BOUNDED = "ACCEPT_BOUNDED"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"
    REFUSE = "REFUSE"
    QUARANTINE = "QUARANTINE"


class LifecycleState(str, Enum):
    REQUEST = "REQUEST"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    AUTHORITY_CHECKED = "AUTHORITY_CHECKED"
    EXECUTING = "EXECUTING"
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
    REVIEWED = "REVIEWED"
    CLOSED = "CLOSED"


LIFECYCLE_ORDER = tuple(LifecycleState)
MAX_QUEUE_DEPTH = 50
MAX_HOPS = 3


def canonical_content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    role: str
    repository: str
    branch: str
    machine_scope: str
    transport: str
    reachable: bool
    capability_classes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernedMessage:
    mission_id: str
    sender_session: str
    recipient_session: str
    intent: str
    requested_capability: str
    content: str
    authority_state: str = "NOT_EVALUATED"
    evidence_refs: tuple[str, ...] = ()
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = None
    ttl_seconds: int = 900
    hop_count: int = 0
    max_hops: int = MAX_HOPS
    sensitivity: str = "INTERNAL"
    message_id: str = field(default_factory=lambda: f"FW-MSG-{uuid4().hex}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence_refs"] = list(self.evidence_refs)
        data["content_hash"] = canonical_content_hash(self.content)
        data["correlation_id"] = self.correlation_id or self.message_id
        data["idempotency_key"] = self.idempotency_key or data["content_hash"]
        return data


def validate_message(message: GovernedMessage, *, now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    if not message.mission_id:
        errors.append("mission_id is required")
    if not message.sender_session or not message.recipient_session:
        errors.append("sender_session and recipient_session are required")
    if message.sender_session == message.recipient_session:
        errors.append("sender and recipient must differ")
    if not message.content.strip():
        errors.append("content must not be empty")
    if message.ttl_seconds <= 0:
        errors.append("ttl_seconds must be positive")
    if message.hop_count < 0 or message.hop_count >= message.max_hops:
        errors.append("message hop limit reached")
    try:
        created = datetime.fromisoformat(message.created_at)
        if created.tzinfo is None:
            errors.append("created_at must include a timezone")
        else:
            current = now or datetime.now(timezone.utc)
            if (current - created).total_seconds() > message.ttl_seconds:
                errors.append("message expired")
    except ValueError:
        errors.append("created_at is not valid ISO-8601")
    return errors


def decide_inbound(
    message: GovernedMessage,
    *,
    recipient: SessionIdentity,
    transport_setting: str,
    authority_permits: bool,
    queue_depth: int,
    seen_idempotency_keys: Iterable[str] = (),
) -> dict:
    """Map transport receipt to a governed disposition; never execute here."""
    errors = validate_message(message)
    key = message.idempotency_key or canonical_content_hash(message.content)
    if errors or key in set(seen_idempotency_keys) or queue_depth >= MAX_QUEUE_DEPTH:
        reason = "; ".join(errors) or ("duplicate message" if key in set(seen_idempotency_keys) else "queue limit reached")
        return {"disposition": InboundDisposition.QUARANTINE.value, "reason": reason, "execute": False}
    if not recipient.reachable or transport_setting == "refuse":
        return {"disposition": InboundDisposition.REFUSE.value, "reason": "recipient unavailable or inbound refused", "execute": False}
    if transport_setting == "hold" or not authority_permits:
        return {"disposition": InboundDisposition.HOLD_FOR_REVIEW.value, "reason": "human review or authority decision required", "execute": False}
    return {"disposition": InboundDisposition.ACCEPT_BOUNDED.value, "reason": "message may enter bounded dispatch evaluation", "execute": False}


def transition_lifecycle(current: LifecycleState, target: LifecycleState, *, evidence_refs: Iterable[str] = ()) -> dict:
    """Permit only the next lifecycle state and require evidence before close."""
    current_index = LIFECYCLE_ORDER.index(current)
    if current_index + 1 >= len(LIFECYCLE_ORDER) or LIFECYCLE_ORDER[current_index + 1] != target:
        raise ValueError(f"invalid lifecycle transition: {current.value} -> {target.value}")
    refs = tuple(evidence_refs)
    if target in {LifecycleState.EVIDENCE_ATTACHED, LifecycleState.CLOSED} and not refs:
        raise ValueError(f"{target.value} requires evidence references")
    return {"from": current.value, "to": target.value, "evidence_refs": list(refs)}


def ledger_record(message: GovernedMessage, event: str, **fields) -> str:
    """Return stable JSONL content for the canonical execution ledger writer."""
    record = {
        "system": "agent_mesh",
        "event": event,
        "message": message.to_dict(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    return json.dumps(record, sort_keys=True)
