"""FW-ADAPTIVE-CAPABILITY-SUBSTRATE-CONVERGENCE-001 Sections 19-22: the
normalized internal communication vocabulary meant to cross PC<->phone
later, without changing its semantics when the transport does (Section
36). This module defines stable, versioned ENVELOPE SHAPES only -- it is
not a transport and does not implement delivery. Adapters around the
already-proven wire primitives (fabric.loopback.wire) remain the future
transport's job, exactly as Section 19 asks ("prefer adapters around
proven wire primitives... do not duplicate existing RemoteCapabilityRequest
fields unnecessarily").

Nine message families (Section 19/20), never conflated:
  COMMAND    -- asks a governed peer to perform an allowed capability.
  EVENT      -- reports something happened; NEVER implies execution.
  ARTIFACT   -- references or transfers an object.
  MEMORY_DELTA -- proposes a state/memory change; NEVER auto-promotes.
  CAPABILITY_ADVERTISEMENT -- reports demonstrable available abilities;
                              carries no invoke()/execute() of its own.
  WORKFLOW   -- carries a WorkflowPlan (or its id) across nodes.
  RESULT     -- reports an execution outcome.
  EVIDENCE_RECEIPT -- reports proof.
  HEARTBEAT  -- reports liveness ONLY; NEVER implies authorization.
  STATE_SUMMARY -- reports a bounded state snapshot.

Common envelope fields (Section 19), deliberately NOT duplicating
RemoteCapabilityRequest's own field set (source_peer_id/relationship_id/
integrity_tag/integrity_key_id already live there and are attached by the
real fabric wire layer when a COMMAND is actually carried inside a
RemoteCapabilityRequest -- this module's envelope wraps AROUND that, it
does not re-specify it):
    message_id, message_type, source_peer_id, destination_node_id,
    created_at, correlation_id, causation_id, objective_id, payload,
    schema_version
"""
from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from evidence_envelope import envelope  # noqa: E402

SCHEMA_VERSION = 1

MSG_COMMAND = "COMMAND"
MSG_EVENT = "EVENT"
MSG_ARTIFACT = "ARTIFACT"
MSG_MEMORY_DELTA = "MEMORY_DELTA"
MSG_CAPABILITY_ADVERTISEMENT = "CAPABILITY_ADVERTISEMENT"
MSG_WORKFLOW = "WORKFLOW"
MSG_RESULT = "RESULT"
MSG_EVIDENCE_RECEIPT = "EVIDENCE_RECEIPT"
MSG_HEARTBEAT = "HEARTBEAT"
MSG_STATE_SUMMARY = "STATE_SUMMARY"
MESSAGE_TYPES = (
    MSG_COMMAND, MSG_EVENT, MSG_ARTIFACT, MSG_MEMORY_DELTA, MSG_CAPABILITY_ADVERTISEMENT,
    MSG_WORKFLOW, MSG_RESULT, MSG_EVIDENCE_RECEIPT, MSG_HEARTBEAT, MSG_STATE_SUMMARY,
)


def _new_id(prefix: str) -> str:
    return envelope.validate_mission_id(f"{prefix}-{uuid.uuid4().hex}")


def _now() -> str:
    return envelope._now()


class EventFabricError(Exception):
    pass


@dataclass(frozen=True)
class MessageEnvelope:
    message_id: str
    message_type: str
    source_peer_id: str
    destination_node_id: str
    payload: dict
    created_at: str = field(default_factory=_now)
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    objective_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        envelope.validate_mission_id(self.message_id)
        if self.message_type not in MESSAGE_TYPES:
            raise EventFabricError(f"unknown message_type {self.message_type!r} (expected one of {MESSAGE_TYPES})")
        if not isinstance(self.payload, dict):
            raise EventFabricError("payload must be a dict")


def _build(message_type: str, *, source_peer_id: str, destination_node_id: str, payload: dict,
           correlation_id: Optional[str] = None, causation_id: Optional[str] = None,
           objective_id: Optional[str] = None) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=_new_id("MSG"), message_type=message_type, source_peer_id=source_peer_id,
        destination_node_id=destination_node_id, payload=payload, correlation_id=correlation_id,
        causation_id=causation_id, objective_id=objective_id,
    )


def build_command(*, source_peer_id: str, destination_node_id: str, capability_id: str,
                   fabric_request_id: str, correlation_id: Optional[str] = None,
                   objective_id: Optional[str] = None) -> MessageEnvelope:
    """A COMMAND envelope names WHICH real fabric RemoteCapabilityRequest
    carries the actual governed ask (by request_id) -- it does not
    duplicate that request's own signed fields."""
    return _build(
        MSG_COMMAND, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"capability_id": capability_id, "fabric_request_id": fabric_request_id},
        correlation_id=correlation_id, objective_id=objective_id,
    )


def build_event(*, source_peer_id: str, destination_node_id: str, description: str,
                 correlation_id: Optional[str] = None) -> MessageEnvelope:
    """Reports that something happened. MUST NEVER be treated as a
    request to execute anything -- see test_event_never_implies_command
    for the enforced distinction (an EVENT envelope carries no
    capability_id/fabric_request_id field at all, so nothing downstream
    can mistake it for a COMMAND)."""
    return _build(
        MSG_EVENT, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"description": description}, correlation_id=correlation_id,
    )


def build_artifact(*, source_peer_id: str, destination_node_id: str, artifact_id: str, sha256: str) -> MessageEnvelope:
    return _build(
        MSG_ARTIFACT, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"artifact_id": artifact_id, "sha256": sha256},
    )


def build_memory_delta(*, source_peer_id: str, destination_node_id: str, proposed_record: dict,
                        target_memory_class: str) -> MessageEnvelope:
    """Proposes a memory change. NEVER auto-promoted -- the receiving
    node must independently run it through MemoryStore.promote_to_*(),
    which itself refuses without qualifying evidence (see substrate.interface)."""
    if target_memory_class not in ("EPISODIC", "SEMANTIC", "PROCEDURAL"):
        raise EventFabricError(f"unknown target_memory_class {target_memory_class!r}")
    return _build(
        MSG_MEMORY_DELTA, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"proposed_record": proposed_record, "target_memory_class": target_memory_class, "promoted": False},
    )


def build_capability_advertisement(*, source_peer_id: str, destination_node_id: str, capability_id: str,
                                    version: str, input_contract: dict, output_contract: dict,
                                    authority_requirement: tuple, availability: str,
                                    evidence_requirement: tuple, capability_state: str) -> MessageEnvelope:
    """Reports a demonstrable ability. This envelope is DATA ONLY -- it
    has no invoke()/execute() method and this module defines no code
    path that treats receiving one as a request to run anything (see
    test_capability_advertisement_cannot_invoke)."""
    return _build(
        MSG_CAPABILITY_ADVERTISEMENT, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={
            "capability_id": capability_id, "version": version, "input_contract": input_contract,
            "output_contract": output_contract, "authority_requirement": list(authority_requirement),
            "availability": availability, "evidence_requirement": list(evidence_requirement),
            "capability_state": capability_state,
        },
    )


def build_workflow(*, source_peer_id: str, destination_node_id: str, workflow_plan_id: str,
                    objective_id: str) -> MessageEnvelope:
    return _build(
        MSG_WORKFLOW, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"workflow_plan_id": workflow_plan_id}, objective_id=objective_id,
    )


def build_result(*, source_peer_id: str, destination_node_id: str, execution_id: str, status: str,
                  correlation_id: Optional[str] = None) -> MessageEnvelope:
    return _build(
        MSG_RESULT, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"execution_id": execution_id, "status": status}, correlation_id=correlation_id,
    )


def build_evidence_receipt(*, source_peer_id: str, destination_node_id: str, evidence_id: str,
                            receipt_id: Optional[str] = None) -> MessageEnvelope:
    return _build(
        MSG_EVIDENCE_RECEIPT, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"evidence_id": evidence_id, "receipt_id": receipt_id},
    )


def build_heartbeat(*, source_peer_id: str, destination_node_id: str) -> MessageEnvelope:
    """Liveness ONLY. This payload shape carries no capability_id, no
    authority, nothing that any governance/execution path in
    substrate.interface reads -- a HEARTBEAT is structurally incapable of
    being mistaken for authorization (see test_heartbeat_never_implies_authorization)."""
    return _build(
        MSG_HEARTBEAT, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"alive": True},
    )


def build_state_summary(*, source_peer_id: str, destination_node_id: str, summary: dict) -> MessageEnvelope:
    return _build(
        MSG_STATE_SUMMARY, source_peer_id=source_peer_id, destination_node_id=destination_node_id,
        payload={"summary": summary},
    )
