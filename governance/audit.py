"""Audit event emission.

Single write path for authority-sensitive events, following the same
append-only-jsonl convention as capabilities/history.jsonl and
router/decisions.jsonl (see those files' own docstrings: "this script is
the single write path into ... -- nothing else should append to that
file by hand"). This module is that single write path for governance
events; no other module in this package should open audit_log.jsonl
directly.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from governance.types import AuditEventFamily

GOVERNANCE_DIR = Path(__file__).resolve().parent
DEFAULT_AUDIT_PATH = GOVERNANCE_DIR / "audit_log.jsonl"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def emit(
    family: AuditEventFamily,
    actor_id: str,
    capability: Optional[str] = None,
    detail: Optional[dict] = None,
    path: Optional[Path] = None,
) -> dict:
    # Resolved dynamically (not as a default-argument value) so that
    # monkeypatching DEFAULT_AUDIT_PATH -- e.g. in tests -- takes effect.
    path = path or DEFAULT_AUDIT_PATH
    event = {
        "event_id": f"EVT-{uuid.uuid4().hex[:12]}",
        "family": family.value,
        "actor_id": actor_id,
        "capability": capability,
        "detail": detail or {},
        "recorded_at": _now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def read_events(path: Optional[Path] = None) -> list[dict]:
    path = path or DEFAULT_AUDIT_PATH
    if not path.exists():
        return []
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
