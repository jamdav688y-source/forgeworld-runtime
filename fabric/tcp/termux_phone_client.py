#!/usr/bin/env python3
"""ForgeWorld PHONE_NODE physical proof client -- for Termux.

STANDALONE BY NECESSITY: the phone does not have this repository, so
this single file duplicates the SMALL amount of wire-format and
receipt-verification logic needed to speak to fabric/tcp/pc_node_server.py,
rather than importing fabric.* (which cannot exist on the phone). This is
a deliberate, documented exception to "reuse, don't duplicate" -- the
duplicated logic is a handful of dict shapes and one hash function, kept
in exact lockstep with fabric/loopback/wire.py and
fabric.interface.compute_receipt_id by comment cross-reference. If those
ever change, this file must change with them.

WHAT THIS SCRIPT DOES, EXACTLY, AND NOTHING ELSE:
  1. builds ONE small text artifact (hardcoded content or --text),
  2. computes its sha256 locally,
  3. sends it as ONE ArtifactEnvelope,
  4. requests EXACTLY the "content_read" capability (hardcoded -- not a
     CLI-controlled arbitrary string, so this can never become a generic
     RPC client),
  5. verifies the response's correlation_id/causation_id/receipt_id
     independently before trusting anything it says,
  6. prints a clear PASS/FAIL verdict and exits.

It never sends a shell command, never evaluates anything the PC returns,
never uses eval/exec/pickle, and never retries automatically -- one
attempt, one verdict.

REQUIREMENTS ON THE PHONE: Termux with `pkg install python` (this uses
only the Python standard library -- multiprocessing.connection, hashlib,
json, base64, uuid -- nothing else needs to be installed).

USAGE (run on the phone, PC's pc_node_server.py already listening):

    python termux_phone_client.py \\
        --host 192.168.1.85 --port 8765 \\
        --authkey <the exact hex string printed when the PC operator
                   started pc_node_server.py> \\
        --pc-node-id PC-NODE-MAIN \\
        --text "hello from a real phone"

The PC operator must start pc_node_server.py FIRST (see
fabric/tcp/pc_node_server.py's own docstring) and share the authkey
out-of-band (read it off their own screen) -- this script never guesses
or hardcodes one.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import uuid
from multiprocessing import connection

PHONE_CAPABILITY_ID = "content_read"  # hardcoded: this client can never request anything else


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


def compute_receipt_id(correlation_id, causation_id, source_node_id, destination_node_id,
                        artifact_id, sha256, capability_id, transfer_state, capability_status) -> str:
    """MUST match fabric.interface.compute_receipt_id() exactly -- same
    field order, same '|' join, same sha256 hex, same 'RCPT-' prefix."""
    canonical = "|".join([
        correlation_id, causation_id, source_node_id, destination_node_id,
        artifact_id, sha256, capability_id, transfer_state, capability_status,
    ])
    return "RCPT-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="ForgeWorld PHONE_NODE physical proof client (Termux).")
    parser.add_argument("--host", required=True, help="the PC's LAN IP, e.g. 192.168.1.85")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--authkey", required=True, help="hex string, exactly as printed by pc_node_server.py")
    parser.add_argument("--pc-node-id", default="PC-NODE-MAIN")
    parser.add_argument("--phone-node-id", default="PHONE-NODE-TERMUX")
    parser.add_argument("--text", default="ForgeWorld PHONE_NODE physical device boundary proof.")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--response-timeout", type=float, default=15.0)
    args = parser.parse_args()

    if len(args.text.encode("utf-8")) > 2000:
        print("REFUSING: --text exceeds this client's own 2000-byte bound", file=sys.stderr)
        return 2

    payload = args.text.encode("utf-8")
    artifact_id = _new_id("ART")
    envelope_id = _new_id("ENV")
    sha256 = hashlib.sha256(payload).hexdigest()
    correlation_id = _new_id("CORR")

    print(f"PHONE: connecting to {args.host}:{args.port} ...")
    try:
        conn = connection.Client((args.host, args.port), family="AF_INET", authkey=bytes.fromhex(args.authkey))
    except OSError as exc:
        print(f"PHONE_RESULT: UNREACHABLE -- could not connect: {exc}", file=sys.stderr)
        return 1
    print("PHONE: connected.")

    try:
        # -- Step 1: transfer the artifact envelope --
        envelope_wire = {
            "envelope_id": envelope_id, "artifact_id": artifact_id, "source_node_id": args.phone_node_id,
            "payload_b64": base64.b64encode(payload).decode("ascii"), "sha256": sha256, "size": len(payload),
            "declared_content_type": "text/plain", "provenance_lineage": [], "created_at": _now(),
        }
        send_message(conn, "ARTIFACT_ENVELOPE", {"for_node_id": args.pc_node_id, "envelope": envelope_wire})
        kind, ack, error = recv_message(conn, timeout=args.response_timeout)
        if error or kind != "ARTIFACT_ENVELOPE_ACK" or not ack.get("delivered"):
            print(f"PHONE_RESULT: TRANSFER_FAILED -- {error or ack}", file=sys.stderr)
            return 1
        print("PHONE: artifact envelope delivered and acknowledged.")

        # -- Step 2: request the one allowlisted capability --
        request_id = _new_id("CAPREQ")
        causation_id = _new_id("XFER")  # this client does not track a separate TransferResult.transfer_id; the PC associates by artifact_id
        authority_wire = {
            "actor_id": args.phone_node_id, "granted_capability_ids": [PHONE_CAPABILITY_ID],
            "granted_by": "termux_operator", "granted_at": _now(), "expires_at": None,
        }
        request_wire = {
            "request_id": request_id, "source_node_id": args.phone_node_id, "destination_node_id": args.pc_node_id,
            "artifact_id": artifact_id, "capability_id": PHONE_CAPABILITY_ID, "authority_context": authority_wire,
            "correlation_id": correlation_id, "causation_id": causation_id, "timeout_seconds": 10, "requested_at": _now(),
        }
        send_message(conn, "CAPABILITY_REQUEST", request_wire)
        kind, response_payload, error = recv_message(conn, timeout=args.response_timeout)
        if error or kind != "CAPABILITY_RESPONSE":
            print(f"PHONE_RESULT: CAPABILITY_REQUEST_FAILED -- {error or kind}", file=sys.stderr)
            return 1

        result = response_payload["result"]
        receipt = response_payload["receipt"]
        print(f"PHONE: received capability result status={result['status']!r}")
        print(json.dumps(response_payload, indent=2))

        # -- Step 3: PHONE_NODE verifies -- transport != trust --
        problems = []
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

        print(f"PHONE_RESULT: PHONE_TO_PC_GOVERNED_ROUND_TRIP_VERIFIED receipt_id={receipt['receipt_id']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
