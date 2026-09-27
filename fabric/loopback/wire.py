"""Wire serialization and message framing for the loopback transport
adapter. This is translation logic ONLY -- it does not redefine any
fabric.interface contract. Every dataclass here is converted to/from a
plain JSON-safe dict using the EXACT field names fabric.interface
already defines; nothing is renamed, added, or removed.

SAFETY: JSON only, never pickle -- a message arriving over this wire is
treated as untrusted input (this is, after all, the seam a real phone
will one day speak through), and JSON cannot construct arbitrary Python
objects or execute code during deserialization the way an unpickle of
attacker-controlled bytes could.

Every `*_from_wire` function has a `safe_*_from_wire` counterpart that
never raises: malformed or truncated input returns (None, "reason")
instead, so callers can report MALFORMED/TRUNCATED honestly rather than
crash. This is where "malformed serialized message" and "truncated
message" are actually caught.
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402
from evidence_envelope import envelope  # noqa: E402

# ---------------------------------------------------------------------------
# message framing: one send_bytes()/recv_bytes() call = one JSON message
# {"kind": "...", "payload": {...}}. multiprocessing.connection already
# frames each send_bytes() as one atomic message -- no manual length
# prefix is needed here.
# ---------------------------------------------------------------------------

def send_message(conn, kind: str, payload: dict) -> None:
    conn.send_bytes(json.dumps({"kind": kind, "payload": payload}).encode("utf-8"))


def recv_message(conn, timeout: float = 10.0, max_bytes: Optional[int] = None):
    """Returns (kind, payload_dict, error). error is None on success and
    is one of the honest failure reasons this mission requires when it
    is not: a bounded wait that finds nothing is TIMEOUT, a closed
    connection is EOF, and undecodable/incomplete bytes are MALFORMED/
    TRUNCATED.

    `max_bytes`, when given, is passed straight through to
    Connection.recv_bytes(maxlength=...) -- the stdlib's own explicit
    message-size bound. Default None preserves the original unbounded
    behavior exactly (existing loopback tests/callers are unaffected);
    a LAN-facing listener (fabric/tcp/) always sets this."""
    try:
        ready = conn.poll(timeout)
    except OSError as exc:
        return None, None, f"transport error while waiting for a message: {exc}"
    if not ready:
        return None, None, f"TIMEOUT: no message received within {timeout}s"
    try:
        raw = conn.recv_bytes(maxlength=max_bytes) if max_bytes is not None else conn.recv_bytes()
    except EOFError:
        return None, None, "EOF: the remote process closed the connection"
    except OSError as exc:
        if max_bytes is not None:
            return None, None, f"MESSAGE_TOO_LARGE: message exceeded the {max_bytes}-byte limit ({exc})"
        return None, None, f"transport error while receiving: {exc}"
    if not raw:
        return None, None, "TRUNCATED: received an empty message"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, None, f"MALFORMED: message is not valid UTF-8: {exc}"
    try:
        msg = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, None, f"MALFORMED: message is not valid JSON (possibly truncated): {exc}"
    if not isinstance(msg, dict) or "kind" not in msg or "payload" not in msg:
        return None, None, "MALFORMED: message is missing the required 'kind'/'payload' envelope structure"
    return msg["kind"], msg["payload"], None


# ---------------------------------------------------------------------------
# ArtifactEnvelope
# ---------------------------------------------------------------------------

def envelope_to_wire(env: "fi.ArtifactEnvelope") -> dict:
    return {
        "envelope_id": env.envelope_id, "artifact_id": env.artifact_id,
        "source_node_id": env.source_node_id,
        "payload_b64": base64.b64encode(bytes(env.payload)).decode("ascii"),
        "sha256": env.sha256, "size": env.size,
        "declared_content_type": env.declared_content_type,
        "provenance_lineage": list(env.provenance_lineage),
        "created_at": env.created_at,
    }


def safe_envelope_from_wire(d: dict):
    try:
        payload = base64.b64decode(d["payload_b64"], validate=True)
        return fi.ArtifactEnvelope(
            envelope_id=d["envelope_id"], artifact_id=d["artifact_id"], source_node_id=d["source_node_id"],
            payload=payload, sha256=d["sha256"], size=d["size"],
            declared_content_type=d.get("declared_content_type"),
            provenance_lineage=tuple(d.get("provenance_lineage", [])),
            created_at=d.get("created_at", fi._now()),
        ), None
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        return None, f"MALFORMED envelope: {exc!r}"


# ---------------------------------------------------------------------------
# AuthorityContext
# ---------------------------------------------------------------------------

def authority_to_wire(ctx: "fi.AuthorityContext") -> dict:
    return dataclasses.asdict(ctx) | {"granted_capability_ids": list(ctx.granted_capability_ids)}


def safe_authority_from_wire(d: dict):
    try:
        return fi.AuthorityContext(
            actor_id=d["actor_id"], granted_capability_ids=tuple(d["granted_capability_ids"]),
            granted_by=d["granted_by"], granted_at=d.get("granted_at", fi._now()),
            expires_at=d.get("expires_at"),
        ), None
    except (KeyError, TypeError) as exc:
        return None, f"MALFORMED authority_context: {exc!r}"


# ---------------------------------------------------------------------------
# RemoteCapabilityRequest
# ---------------------------------------------------------------------------

def capability_request_to_wire(req: "fi.RemoteCapabilityRequest") -> dict:
    return {
        "request_id": req.request_id, "source_node_id": req.source_node_id,
        "destination_node_id": req.destination_node_id, "artifact_id": req.artifact_id,
        "capability_id": req.capability_id, "authority_context": authority_to_wire(req.authority_context),
        "correlation_id": req.correlation_id, "causation_id": req.causation_id,
        "timeout_seconds": req.timeout_seconds, "requested_at": req.requested_at,
        "integrity_tag": req.integrity_tag, "integrity_key_id": req.integrity_key_id,
    }


def safe_capability_request_from_wire(d: dict):
    try:
        authority, reason = safe_authority_from_wire(d["authority_context"])
        if authority is None:
            return None, reason
        return fi.RemoteCapabilityRequest(
            request_id=d["request_id"], source_node_id=d["source_node_id"],
            destination_node_id=d["destination_node_id"], artifact_id=d["artifact_id"],
            capability_id=d["capability_id"], authority_context=authority,
            correlation_id=d["correlation_id"], causation_id=d["causation_id"],
            timeout_seconds=d["timeout_seconds"], requested_at=d.get("requested_at", fi._now()),
            integrity_tag=d.get("integrity_tag"), integrity_key_id=d.get("integrity_key_id"),
        ), None
    except (KeyError, TypeError) as exc:
        return None, f"MALFORMED capability_request: {exc!r}"


# ---------------------------------------------------------------------------
# (RemoteCapabilityResult, FabricReceipt) pair
# ---------------------------------------------------------------------------

def capability_response_to_wire(result: "fi.RemoteCapabilityResult", receipt: "fi.FabricReceipt") -> dict:
    return {
        "result": {
            "request_id": result.request_id, "capability_id": result.capability_id, "status": result.status,
            "structured_result": result.structured_result, "error_detail": result.error_detail,
            "source_node_id": result.source_node_id, "destination_node_id": result.destination_node_id,
            "correlation_id": result.correlation_id, "causation_id": result.causation_id,
            "produced_at": result.produced_at,
        },
        "receipt": receipt.to_dict(),
    }


def safe_capability_response_from_wire(d: dict):
    try:
        r = d["result"]
        result = fi.RemoteCapabilityResult(
            request_id=r["request_id"], capability_id=r["capability_id"], status=r["status"],
            structured_result=r["structured_result"], error_detail=r.get("error_detail"),
            source_node_id=r["source_node_id"], destination_node_id=r["destination_node_id"],
            correlation_id=r["correlation_id"], causation_id=r["causation_id"],
            produced_at=r.get("produced_at", fi._now()),
        )
        rc = d["receipt"]
        receipt = fi.FabricReceipt(
            receipt_id=rc["receipt_id"], correlation_id=rc["correlation_id"], causation_id=rc["causation_id"],
            source_node_id=rc["source_node_id"], destination_node_id=rc["destination_node_id"],
            artifact_id=rc["artifact_id"], sha256=rc["sha256"], capability_id=rc["capability_id"],
            transfer_state=rc["transfer_state"], capability_status=rc["capability_status"],
            generated_at=rc.get("generated_at", fi._now()),
        )
        return result, receipt, None
    except (KeyError, TypeError, fi.FabricError, envelope.InvalidMissionIdError) as exc:
        return None, None, f"MALFORMED capability_response: {exc!r}"
