#!/usr/bin/env python3
"""PC_NODE loopback server: PROCESS B in the FW-FABRIC-TRANSPORT-LOOPBACK-001
proof. Runs as a genuinely separate OS process (spawned via subprocess by
the test), listens on one OS-appropriate loopback address (AF_UNIX here;
AF_PIPE on Windows, per fabric.loopback.transport.make_loopback_address),
and answers exactly the message kinds the loopback wire protocol defines.

Every step this script performs delegates to ALREADY-EXISTING, unmodified
fabric.interface / artifact_handoff / content_readers machinery:
process_remote_capability_request() does the real work (hash
verification, provenance via artifact_handoff.handoff(), lineage
recording, authority check, capability dispatch, deterministic receipt).
This script's only job is to move bytes across the process boundary and
call that function locally with a local InMemoryFabricTransport standing
in for "this node's own inbox."

Bounded by design: accepts exactly one connection, stops after
--max-messages messages (default 100) or --idle-timeout seconds without
a message (default 15s), and always exits on a SHUTDOWN message. This is
a test fixture process, not a long-lived service.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from multiprocessing import connection
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402
from fabric.transports import InMemoryFabricTransport  # noqa: E402
from fabric.loopback import wire  # noqa: E402
from fabric import capabilities as fabric_capabilities  # noqa: E402,F401 -- registers content_read/echo_mock
from artifact_handoff.lineage_store import LineageStore  # noqa: E402


def _handle_artifact_envelope(payload: dict, node_id: str, local_transport: InMemoryFabricTransport) -> dict:
    for_node_id = payload.get("for_node_id")
    if for_node_id != node_id:
        return {"delivered": False, "reason": f"unknown node: this listener identifies as {node_id!r}, not {for_node_id!r}"}
    env, reason = wire.safe_envelope_from_wire(payload.get("envelope", {}))
    if env is None:
        return {"delivered": False, "reason": reason}
    outcome = local_transport.deliver(node_id, env)
    return outcome


def _handle_capability_request(payload: dict, node_id: str, local_transport, lineage_store, artifact_index):
    request, reason = wire.safe_capability_request_from_wire(payload)
    if request is None:
        # Cannot build a proper (result, receipt) pair without a valid
        # request to key it off of -- report the framing failure directly.
        return None, reason
    if request.destination_node_id != node_id:
        result, receipt = fi._result_and_receipt(
            request, status=fi.CAP_FAILED, structured_result=None,
            error_detail=f"unknown node: this listener identifies as {node_id!r}, not {request.destination_node_id!r}",
        )
        return (result, receipt), None
    result, receipt = fi.process_remote_capability_request(
        request, local_transport, lineage_store=lineage_store, artifact_index=artifact_index,
    )
    return (result, receipt), None


class _AlwaysIncompleteTestCapability:
    """TEST-ONLY capability, registered unconditionally alongside the
    real ones: claims COMPLETED but returns no structured_result. Exists
    so "incomplete result" can be proven to survive a real subprocess
    round trip, exercising process_remote_capability_request()'s
    EXISTING (unmodified) incomplete-detection logic from across the
    process boundary rather than only in-process."""

    capability_id = "broken_incomplete_capability_for_testing"

    def invoke(self, manifest_dict, payload):
        return fi.CAP_COMPLETED, None, None


def run_server(address: str, family: str, authkey: bytes, node_id: str, lineage_dir: str,
               max_messages: int = 100, idle_timeout: float = 15.0) -> None:
    lineage_store = LineageStore(Path(lineage_dir))
    artifact_index = fi.FabricArtifactIndex()
    local_transport = InMemoryFabricTransport(registered_nodes=(node_id,))
    fi.register_capability(_AlwaysIncompleteTestCapability())

    listener = connection.Listener(address, family=family, authkey=authkey, backlog=1)
    print(f"PC_NODE_LISTENING {address}", flush=True)
    try:
        conn = listener.accept()
    finally:
        listener.close()

    print("PC_NODE_ACCEPTED", flush=True)
    handled = 0
    try:
        while handled < max_messages:
            kind, payload, error = wire.recv_message(conn, timeout=idle_timeout)
            if error is not None:
                print(f"PC_NODE_RECV_ERROR {error}", flush=True)
                break
            handled += 1
            if kind == "SHUTDOWN":
                print("PC_NODE_SHUTDOWN_RECEIVED", flush=True)
                break
            elif kind == "TEST_HOOK":
                # Deterministic test support only -- not part of the real
                # wire protocol. "die" simulates process termination
                # mid-request (no response is ever sent); "sleep_ms"
                # simulates a slow/hung PC_NODE for bounded-timeout tests.
                action = payload.get("action")
                if action == "die":
                    os._exit(1)
                elif action == "sleep_ms":
                    time.sleep(payload.get("ms", 0) / 1000.0)
                    wire.send_message(conn, "TEST_HOOK_ACK", {})
            elif kind == "ARTIFACT_ENVELOPE":
                outcome = _handle_artifact_envelope(payload, node_id, local_transport)
                wire.send_message(conn, "ARTIFACT_ENVELOPE_ACK", outcome)
            elif kind == "CAPABILITY_REQUEST":
                pair, framing_error = _handle_capability_request(payload, node_id, local_transport, lineage_store, artifact_index)
                if pair is None:
                    wire.send_message(conn, "CAPABILITY_RESPONSE_ERROR", {"reason": framing_error})
                else:
                    result, receipt = pair
                    wire.send_message(conn, "CAPABILITY_RESPONSE", wire.capability_response_to_wire(result, receipt))
            else:
                wire.send_message(conn, "PROTOCOL_ERROR", {"reason": f"unrecognized message kind {kind!r}"})
    finally:
        conn.close()
    print("PC_NODE_EXITING", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--authkey", required=True, help="hex-encoded shared secret")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--lineage-dir", required=True)
    parser.add_argument("--max-messages", type=int, default=100)
    parser.add_argument("--idle-timeout", type=float, default=15.0)
    args = parser.parse_args()

    run_server(
        address=args.address, family=args.family, authkey=bytes.fromhex(args.authkey),
        node_id=args.node_id, lineage_dir=args.lineage_dir,
        max_messages=args.max_messages, idle_timeout=args.idle_timeout,
    )


if __name__ == "__main__":
    main()
