#!/usr/bin/env python3
"""ForgeWorld PHONE_NODE physical_ping client -- for Termux (MISSION:
FW-PHYSICAL-ANDROID-PC-PAIRING-001).

STANDALONE BY NECESSITY, same reason and same discipline as
fabric/tcp/termux_phone_client.py: the phone does not have this
repository, so this file duplicates the small amount of wire-format,
canonical-signing, and receipt-verification logic needed to speak to
fabric/tcp/pc_node_server.py (started with --capability physical_ping
--pairing-store-dir ... --key-store-dir ... --peer-store-dir ...),
rather than importing fabric.* (which cannot exist on the phone). The
duplicated logic is kept in EXACT lockstep with fabric/interface.py's
canonical_request_fields() / compute_request_integrity_tag() and
fabric/loopback/wire.py's wire dict shapes, by comment cross-reference.
If those ever change, this file must change with them --
fabric/tcp/tests/test_termux_physical_ping_client_vectors.py enforces
byte-for-byte parity against the real fabric.interface functions for a
set of known vectors, so a divergence fails CI rather than only being
caught physically.

UNLIKE termux_phone_client.py (which speaks the older, integrity-optional
wire shape), this script ALWAYS signs its request and ALWAYS carries
relationship_id/source_peer_id -- the physical proof this mission
requires is of the FULL gate chain (message integrity + pairing
relationship + peer identity + replay + authority), not merely of
reachability.

WHAT THIS SCRIPT DOES, EXACTLY, AND NOTHING ELSE:
  1. builds ONE small text artifact: a fresh random nonce (hardcoded
     shape, or --nonce to supply your own for a tamper/adversarial test),
  2. computes its sha256 locally,
  3. sends it as ONE ArtifactEnvelope,
  4. builds ONE physical_ping capability request (hardcoded capability_id
     -- not CLI-controlled, so this can never become a generic RPC
     client), HMAC-SHA256-signs it under the secret key material the
     operator transcribed from fabric/tcp/pc_pairing_ceremony.py's
     `offer` output,
  5. verifies the response's correlation_id/causation_id/receipt_id AND
     the echoed nonce independently before trusting anything it says,
  6. prints a clear PASS/FAIL verdict and exits.

It never sends a shell command, never evaluates anything the PC returns,
never uses eval/exec/pickle, and never retries automatically -- one
attempt, one verdict.

REQUIREMENTS ON THE PHONE: Termux with `pkg install python` -- stdlib
only (multiprocessing.connection, hashlib, hmac, json, base64, uuid).

CONFIG: pass either a JSON --config file (written once by hand from the
PC operator's pairing-ceremony + pc_node_server.py output) or all of the
individual flags. The JSON shape:
    {
      "host": "192.168.1.85", "port": 8765, "authkey": "<hex>",
      "pc_node_id": "PC-NODE-MAIN", "phone_node_id": "PHONE-NODE-TERMUX",
      "relationship_id": "REL-...", "integrity_key_id": "IKEY-...",
      "integrity_key_hex": "<hex, from pc_pairing_ceremony.py offer>",
      "source_peer_id": "PEER-...", "granted_capability_ids": ["physical_ping"]
    }
The secret (integrity_key_hex) never leaves this file and this process's
memory -- it is not sent on the wire (integrity_key_id, which is NOT
secret, is sent instead; the PC resolves the same secret from its own
LocalKeyStore to verify the tag).

USAGE:
    python termux_physical_ping_client.py --config phone_config.json
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import sys
import time
import uuid
from multiprocessing import connection
from pathlib import Path

PHONE_CAPABILITY_ID = "physical_ping"  # hardcoded: this client can never request anything else


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def send_message(conn, kind: str, payload: dict) -> None:
    conn.send_bytes(json.dumps({"kind": kind, "payload": payload}).encode("utf-8"))


def recv_message(conn, timeout: float = 10.0):
    if not conn.poll(timeout):
        return None, None, f"TIMEOUT: no message received within {timeout}s"
    try:
        raw = conn.recv_bytes()
    except EOFError:
        return None, None, "EOF: the PC closed the connection"
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, f"MALFORMED response: {exc}"
    if not isinstance(msg, dict) or "kind" not in msg or "payload" not in msg:
        return None, None, "MALFORMED response: missing kind/payload"
    return msg["kind"], msg["payload"], None


def canonical_json(obj) -> bytes:
    """MUST match evidence_envelope.envelope._canonical() exactly:
    json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def canonical_request_fields(request: dict) -> dict:
    """MUST match fabric.interface.canonical_request_fields() exactly --
    same field set, same nesting, same key names. request here is the
    plain dict this script itself builds (see build_request()), not a
    dataclass, so this simply selects/reshapes the same fields."""
    return {
        "request_id": request["request_id"],
        "source_node_id": request["source_node_id"],
        "destination_node_id": request["destination_node_id"],
        "artifact_id": request["artifact_id"],
        "capability_id": request["capability_id"],
        "authority_context": {
            "actor_id": request["authority_context"]["actor_id"],
            "granted_capability_ids": list(request["authority_context"]["granted_capability_ids"]),
            "granted_by": request["authority_context"]["granted_by"],
            "granted_at": request["authority_context"]["granted_at"],
            "expires_at": request["authority_context"]["expires_at"],
        },
        "correlation_id": request["correlation_id"],
        "causation_id": request["causation_id"],
        "timeout_seconds": request["timeout_seconds"],
        "requested_at": request["requested_at"],
        "relationship_id": request["relationship_id"],
        "source_peer_id": request["source_peer_id"],
    }


def compute_request_integrity_tag(request: dict, key: bytes) -> str:
    """MUST match fabric.interface.compute_request_integrity_tag()
    exactly: HMAC-SHA256 over canonical_json(canonical_request_fields(request))."""
    canonical = canonical_json(canonical_request_fields(request))
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def compute_receipt_id(correlation_id, causation_id, source_node_id, destination_node_id,
                        artifact_id, sha256, capability_id, transfer_state, capability_status) -> str:
    """MUST match fabric.interface.compute_receipt_id() exactly -- same
    field order, same '|' join, same sha256 hex, same 'RCPT-' prefix."""
    canonical = "|".join([
        correlation_id, causation_id, source_node_id, destination_node_id,
        artifact_id, sha256, capability_id, transfer_state, capability_status,
    ])
    return "RCPT-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_request(*, request_id, source_node_id, destination_node_id, artifact_id,
                   correlation_id, causation_id, relationship_id, source_peer_id,
                   integrity_key_id, granted_capability_ids) -> dict:
    return {
        "request_id": request_id, "source_node_id": source_node_id,
        "destination_node_id": destination_node_id, "artifact_id": artifact_id,
        "capability_id": PHONE_CAPABILITY_ID,
        "authority_context": {
            "actor_id": source_node_id, "granted_capability_ids": list(granted_capability_ids),
            "granted_by": "termux_operator", "granted_at": _now(), "expires_at": None,
        },
        "correlation_id": correlation_id, "causation_id": causation_id,
        "timeout_seconds": 10, "requested_at": _now(),
        "integrity_tag": None, "integrity_key_id": integrity_key_id,
        "relationship_id": relationship_id, "source_peer_id": source_peer_id,
    }


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="ForgeWorld PHONE_NODE physical_ping client (Termux).")
    parser.add_argument("--config", default=None, help="JSON config file; see this script's own docstring for the shape")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--authkey", default=None, help="hex string, exactly as printed by pc_node_server.py")
    parser.add_argument("--pc-node-id", default=None)
    parser.add_argument("--phone-node-id", default=None)
    parser.add_argument("--relationship-id", default=None)
    parser.add_argument("--integrity-key-id", default=None)
    parser.add_argument("--integrity-key-hex", default=None)
    parser.add_argument("--source-peer-id", default=None)
    parser.add_argument("--nonce", default=None, help="default: a fresh random nonce")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--response-timeout", type=float, default=15.0)
    args = parser.parse_args()

    cfg = load_config(args.config) if args.config else {}

    def _get(name, flag_value, required=True, default=None):
        value = flag_value if flag_value is not None else cfg.get(name, default)
        if required and value is None:
            print(f"REFUSING: missing required setting {name!r} (pass --{name.replace('_', '-')} or set it in --config)", file=sys.stderr)
            raise SystemExit(2)
        return value

    host = _get("host", args.host)
    port = int(_get("port", args.port))
    authkey_hex = _get("authkey", args.authkey)
    pc_node_id = _get("pc_node_id", args.pc_node_id, default="PC-NODE-MAIN")
    phone_node_id = _get("phone_node_id", args.phone_node_id, default="PHONE-NODE-TERMUX")
    relationship_id = _get("relationship_id", args.relationship_id)
    integrity_key_id = _get("integrity_key_id", args.integrity_key_id)
    integrity_key_hex = _get("integrity_key_hex", args.integrity_key_hex)
    source_peer_id = _get("source_peer_id", args.source_peer_id)
    granted_capability_ids = cfg.get("granted_capability_ids", [PHONE_CAPABILITY_ID])

    nonce_text = args.nonce if args.nonce is not None else f"forgeworld-physical-ping-{uuid.uuid4().hex}"
    payload = nonce_text.encode("utf-8")
    artifact_id = _new_id("ART")
    envelope_id = _new_id("ENV")
    sha256 = hashlib.sha256(payload).hexdigest()
    correlation_id = _new_id("CORR")
    request_id = _new_id("CAPREQ")
    causation_id = _new_id("XFER")

    request = build_request(
        request_id=request_id, source_node_id=phone_node_id, destination_node_id=pc_node_id,
        artifact_id=artifact_id, correlation_id=correlation_id, causation_id=causation_id,
        relationship_id=relationship_id, source_peer_id=source_peer_id,
        integrity_key_id=integrity_key_id, granted_capability_ids=granted_capability_ids,
    )
    tag = compute_request_integrity_tag(request, bytes.fromhex(integrity_key_hex))
    request["integrity_tag"] = tag

    print(f"PHONE: connecting to {host}:{port} ...")
    try:
        conn = connection.Client((host, port), family="AF_INET", authkey=bytes.fromhex(authkey_hex))
    except OSError as exc:
        print(f"PHONE_RESULT: UNREACHABLE -- could not connect: {exc}", file=sys.stderr)
        return 1
    print("PHONE: connected.")

    try:
        envelope_wire = {
            "envelope_id": envelope_id, "artifact_id": artifact_id, "source_node_id": phone_node_id,
            "payload_b64": base64.b64encode(payload).decode("ascii"), "sha256": sha256, "size": len(payload),
            "declared_content_type": "text/plain", "provenance_lineage": [], "created_at": _now(),
        }
        send_message(conn, "ARTIFACT_ENVELOPE", {"for_node_id": pc_node_id, "envelope": envelope_wire})
        kind, ack, error = recv_message(conn, timeout=args.response_timeout)
        if error or kind != "ARTIFACT_ENVELOPE_ACK" or not ack.get("delivered"):
            print(f"PHONE_RESULT: TRANSFER_FAILED -- {error or ack}", file=sys.stderr)
            return 1
        print("PHONE: artifact envelope delivered and acknowledged.")

        request_wire = dict(request)
        send_message(conn, "CAPABILITY_REQUEST", request_wire)
        kind, response_payload, error = recv_message(conn, timeout=args.response_timeout)
        if error or kind != "CAPABILITY_RESPONSE":
            print(f"PHONE_RESULT: CAPABILITY_REQUEST_FAILED -- {error or kind}", file=sys.stderr)
            return 1

        result = response_payload["result"]
        receipt = response_payload["receipt"]
        print(f"PHONE: received capability result status={result['status']!r}")
        print(json.dumps(response_payload, indent=2))

        problems = []
        if result["status"] != "COMPLETED":
            problems.append(f"result.status is {result['status']!r}, not COMPLETED: {result.get('error_detail')}")
        else:
            echoed = (result.get("structured_result") or {}).get("echoed_nonce")
            if echoed != nonce_text:
                problems.append(f"echoed_nonce mismatch: sent {nonce_text!r}, received {echoed!r}")
        if result["request_id"] != request_id:
            problems.append("result.request_id mismatch")
        if result["correlation_id"] != correlation_id:
            problems.append("result.correlation_id mismatch")
        if result["causation_id"] != request_id:
            problems.append("result.causation_id does not point back to this request")
        if receipt["correlation_id"] != correlation_id:
            problems.append("receipt.correlation_id mismatch")
        if receipt["causation_id"] != request_id:
            problems.append("receipt.causation_id does not point back to this request")
        if receipt["artifact_id"] != artifact_id:
            problems.append("receipt.artifact_id mismatch")
        expected_receipt_id = compute_receipt_id(
            receipt["correlation_id"], receipt["causation_id"], receipt["source_node_id"], receipt["destination_node_id"],
            receipt["artifact_id"], receipt["sha256"], receipt["capability_id"], receipt["transfer_state"], receipt["capability_status"],
        )
        if receipt["receipt_id"] != expected_receipt_id:
            problems.append(f"receipt_id mismatch: got {receipt['receipt_id']}, independently recomputed {expected_receipt_id}")

        try:
            send_message(conn, "SHUTDOWN", {})
        except OSError:
            pass

        if problems:
            print("PHONE_RESULT: VERIFICATION_FAILED -- " + "; ".join(problems), file=sys.stderr)
            return 1

        print(f"PHONE_RESULT: PHONE_TO_PC_GOVERNED_PHYSICAL_PING_VERIFIED receipt_id={receipt['receipt_id']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
