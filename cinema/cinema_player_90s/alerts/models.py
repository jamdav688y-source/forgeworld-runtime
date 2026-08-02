"""Alert data model. See alerts/engine.py for the pipeline that produces
and mutates these."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any

SOURCES = ["renderer", "validator", "player", "storage_monitor", "launcher", "connector_adapter", "operator"]

CLASS_PASSIVE = "PASSIVE"
CLASS_ACTIVE_WARNING = "ACTIVE_WARNING"
CLASS_BLOCKING = "BLOCKING"
CLASSES = [CLASS_PASSIVE, CLASS_ACTIVE_WARNING, CLASS_BLOCKING]

CODES_BY_CLASS = {
    CLASS_PASSIVE: ["progress", "render_complete", "validation_passed", "export_ready"],
    CLASS_ACTIVE_WARNING: [
        "low_storage", "missing_optional_asset", "audio_mismatch",
        "incomplete_frame_range", "device_validation_required",
    ],
    CLASS_BLOCKING: [
        "corrupt_frame", "missing_frame", "invalid_duration", "overwrite_risk",
        "private_data_detected", "invalid_codec", "unresolved_path_conflict",
        "unsafe_publication_attempt",
    ],
}

STATE_DETECTED = "DETECTED"
STATE_CLASSIFIED = "CLASSIFIED"
STATE_PRESENTED = "PRESENTED"
STATE_ACKNOWLEDGED = "ACKNOWLEDGED"
STATE_ACTIONED = "ACTIONED"
STATE_RESOLVED = "RESOLVED"
STATE_DISMISSED = "DISMISSED"
STATE_ESCALATED = "ESCALATED"
STATES = [STATE_DETECTED, STATE_CLASSIFIED, STATE_PRESENTED, STATE_ACKNOWLEDGED,
          STATE_ACTIONED, STATE_RESOLVED, STATE_DISMISSED, STATE_ESCALATED]

TERMINAL_STATES = {STATE_RESOLVED, STATE_DISMISSED}

_SEVERITY_BASE = {CLASS_PASSIVE: 0, CLASS_ACTIVE_WARNING: 10, CLASS_BLOCKING: 100}


def severity_score(alert_class: str, code: str) -> int:
    base = _SEVERITY_BASE[alert_class]
    # stable per-code tiebreaker so ranking is deterministic, not code-order-dependent
    codes = CODES_BY_CLASS[alert_class]
    tiebreak = codes.index(code) if code in codes else 0
    return base + tiebreak


def dedup_key(source: str, code: str, group_key: str | None) -> str:
    raw = f"{source}:{code}:{group_key or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Alert:
    id: str
    source: str
    code: str
    alert_class: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    group_key: str | None = None
    severity: int = 0
    state: str = STATE_DETECTED
    occurrence_count: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    acknowledged_by: str | None = None
    acknowledged_at: float | None = None
    actioned_note: str | None = None
    actioned_at: float | None = None
    resolution_evidence: str | None = None
    resolved_at: float | None = None
    dismissed_reason: str | None = None
    dismissed_at: float | None = None
    escalated_reason: str | None = None
    escalated_at: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Alert":
        return cls(**data)
