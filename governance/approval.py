"""Approval-request objects and lifecycle.

Approval to perform one action must not implicitly authorize future
equivalent actions unless a policy explicitly says so (mission section 9).
This module enforces that by making every approval single-use: once an
approval transitions to EXECUTED, it cannot back it a second execution --
a new REQUIRES_APPROVAL authority check produces a brand new approval
request.

Storage follows the append-only-jsonl convention already used by this
repository (capabilities/history.jsonl, router/decisions.jsonl): every
state transition is a new line, and "current state" is the latest line
for a given approval_id. Nothing rewrites history in place.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from governance.types import ApprovalStatus

GOVERNANCE_DIR = Path(__file__).resolve().parent
DEFAULT_APPROVALS_PATH = GOVERNANCE_DIR / "approvals.jsonl"


@dataclass
class ApprovalRequest:
    approval_id: str
    requested_by: str
    capability: str
    target: dict
    reason: str
    risk: str
    proposed_action: str
    evidence_summary: list
    status: ApprovalStatus
    created_at: str
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    decision_reason: Optional[str] = None
    expires_at: Optional[str] = None
    executed_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append(record: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def _read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def request_approval(
    requested_by: str,
    capability: str,
    target: dict,
    reason: str,
    risk: str,
    proposed_action: str,
    evidence_summary: Optional[list] = None,
    expires_in_seconds: Optional[int] = 86400,
    path: Optional[Path] = None,
) -> ApprovalRequest:
    path = path or DEFAULT_APPROVALS_PATH
    approval_id = f"APR-{uuid.uuid4().hex[:12]}"
    now = _now()
    expires_at = None
    if expires_in_seconds is not None:
        expires_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in_seconds)
        )
    req = ApprovalRequest(
        approval_id=approval_id,
        requested_by=requested_by,
        capability=capability,
        target=target,
        reason=reason,
        risk=risk,
        proposed_action=proposed_action,
        evidence_summary=evidence_summary or [],
        status=ApprovalStatus.PENDING,
        created_at=now,
        expires_at=expires_at,
    )
    _append(req.to_dict(), path)
    return req


def _latest_by_id(path: Path) -> dict:
    latest: dict[str, dict] = {}
    for record in _read_all(path):
        latest[record["approval_id"]] = record
    return latest


def get_current_state(approval_id: str, path: Optional[Path] = None) -> Optional[ApprovalRequest]:
    path = path or DEFAULT_APPROVALS_PATH
    latest = _latest_by_id(path)
    record = latest.get(approval_id)
    if record is None:
        return None
    record = dict(record)
    record["status"] = ApprovalStatus(record["status"])
    return ApprovalRequest(**record)


def _effective_status(req: ApprovalRequest) -> ApprovalRequest:
    """Apply lazy expiry: a PENDING request past its expires_at reads as EXPIRED."""
    if req.status == ApprovalStatus.PENDING and req.expires_at is not None and _now() > req.expires_at:
        req.status = ApprovalStatus.EXPIRED
    return req


def decide_approval(
    approval_id: str,
    decision: ApprovalStatus,
    decided_by: str,
    decider_kind: str,
    reason: str = "",
    path: Optional[Path] = None,
) -> ApprovalRequest:
    """Move a PENDING approval to APPROVED or DENIED.

    Enforces that only a human decider may approve or deny -- an agent
    cannot grant its own (or another agent's) approval. This is the
    approval-side half of the self-escalation guard; see
    delegation.guard_self_escalation() for the policy-editing half.
    """
    path = path or DEFAULT_APPROVALS_PATH
    if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.DENIED):
        raise ValueError("decide_approval only accepts APPROVED or DENIED")

    current = get_current_state(approval_id, path)
    if current is None:
        raise KeyError(f"No approval request '{approval_id}' found")
    current = _effective_status(current)
    if current.status != ApprovalStatus.PENDING:
        raise ValueError(
            f"Approval '{approval_id}' is {current.status.value}, not PENDING; cannot decide."
        )

    if decider_kind != "human":
        raise PermissionError(
            "Only a human decider may approve or deny a REQUIRES_APPROVAL request. "
            f"Rejected attempt by actor_kind='{decider_kind}' (decided_by='{decided_by}')."
        )

    current.status = decision
    current.decided_by = decided_by
    current.decided_at = _now()
    current.decision_reason = reason
    _append(current.to_dict(), path)
    return current


def cancel_approval(approval_id: str, cancelled_by: str, path: Optional[Path] = None) -> ApprovalRequest:
    path = path or DEFAULT_APPROVALS_PATH
    current = get_current_state(approval_id, path)
    if current is None:
        raise KeyError(f"No approval request '{approval_id}' found")
    current = _effective_status(current)
    if current.status not in (ApprovalStatus.PENDING,):
        raise ValueError(f"Approval '{approval_id}' is {current.status.value}; cannot cancel.")
    current.status = ApprovalStatus.CANCELLED
    current.decided_by = cancelled_by
    current.decided_at = _now()
    current.decision_reason = "cancelled"
    _append(current.to_dict(), path)
    return current


def mark_executed(approval_id: str, path: Optional[Path] = None) -> ApprovalRequest:
    """One-shot consumption: an APPROVED request may be executed exactly once."""
    path = path or DEFAULT_APPROVALS_PATH
    current = get_current_state(approval_id, path)
    if current is None:
        raise KeyError(f"No approval request '{approval_id}' found")
    current = _effective_status(current)
    if current.status != ApprovalStatus.APPROVED:
        raise ValueError(
            f"Approval '{approval_id}' is {current.status.value}, not APPROVED; refusing to execute. "
            "An approval may back exactly one execution."
        )
    current.status = ApprovalStatus.EXECUTED
    current.executed_at = _now()
    _append(current.to_dict(), path)
    return current


def find_active_approval(
    capability: str,
    target: dict,
    requested_by: str,
    path: Optional[Path] = None,
) -> Optional[ApprovalRequest]:
    """Find an APPROVED-but-not-yet-executed request for this exact
    (capability, target, requester) triple. Does not match PENDING,
    DENIED, EXPIRED, CANCELLED, or already-EXECUTED requests -- each of
    those requires a fresh approval cycle.
    """
    path = path or DEFAULT_APPROVALS_PATH
    latest = _latest_by_id(path)
    for record in latest.values():
        if (
            record["capability"] == capability
            and record["target"] == target
            and record["requested_by"] == requested_by
            and record["status"] == ApprovalStatus.APPROVED.value
        ):
            record = dict(record)
            record["status"] = ApprovalStatus(record["status"])
            req = ApprovalRequest(**record)
            return _effective_status(req)
    return None
