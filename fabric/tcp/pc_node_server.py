#!/usr/bin/env python3
"""PC_NODE TCP listener: the real-network-facing PC-side half of
FW-FABRIC-DEVICE-BOUNDARY-001, replacing the SIMULATED phone<->PC
process boundary (fabric/loopback/) with a real TCP socket a physical
Termux PHONE_NODE can reach over LAN Wi-Fi.

TCP IS AN ADAPTER, NOT THE ARCHITECTURE: this script adds no new fabric
contract, no new capability logic, no new authority model. It reuses,
completely unmodified:

  - fabric.interface.process_remote_capability_request() -- the real
    work (independent hash re-verification, provenance via
    artifact_handoff.handoff(), lineage recording, authority check,
    capability dispatch, deterministic receipt).
  - fabric.loopback.wire -- the exact same JSON wire format the
    same-machine loopback proof already validated (FW-FABRIC-TRANSPORT-
    LOOPBACK-001), including its 17/17-tested malformed/truncated/
    timeout/EOF handling.
  - fabric.transports.InMemoryFabricTransport -- this node's own inbox.
  - fabric.capabilities.ContentReadCapability -- the one real capability
    this listener will invoke.
  - artifact_handoff.lineage_store.LineageStore -- durable provenance.

The only genuinely new code here is TCP-specific hardening a
same-machine test fixture doesn't need:

  - binds to an EXPLICIT host:port the operator supplies on the command
    line -- there is no default, and 0.0.0.0/:: is refused outright.
  - registers ONLY "content_read". Importing fabric.capabilities
    registers "echo_mock" too as an import side effect (unmodified,
    upstream behavior) -- this script explicitly removes "echo_mock"
    from the registry immediately after import, so this listener can
    never invoke anything but the one allowlisted capability.
  - every request's capability_id is checked against that allowlist a
    SECOND time at dispatch (defense in depth, not just registry
    absence).
  - bounds each message to --max-message-bytes (default 65536) via
    wire.recv_message()'s max_bytes parameter.
  - bounds total session wall-clock time via --max-runtime-seconds, in
    addition to the existing per-message --idle-timeout.
  - accepts EXACTLY ONE connection, then closes the listening socket
    immediately -- no re-accept loop, ever. This is a one-shot listener,
    matching the discipline the operator's own PowerShell probe already
    demonstrated (temporary firewall rule, one transaction, teardown).
  - contains NO test hook, no debug backdoor, no way to crash or
    reconfigure this process from received data, no eval/exec, no
    pickle, no shell invocation of any kind.

FIREWALL / LIFECYCLE: this script never touches Windows Firewall rules
itself and never will. The operator opens a rule scoped to the exact
port before starting this script and removes it immediately after the
script exits -- the same one-shot pattern already validated by the raw
TCP probe this mission's brief describes. This script's own bounded
lifecycle (one connection, bounded messages, bounded runtime) exists
precisely so that discipline has a natural, short window to work within.
"""
from __future__ import annotations

import argparse
import sys
import time
from multiprocessing import connection
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402
from fabric.transports import InMemoryFabricTransport  # noqa: E402
from fabric.loopback import wire  # noqa: E402
from fabric import capabilities as fabric_capabilities  # noqa: E402 -- import registers content_read AND echo_mock; echo_mock is removed below
from artifact_handoff.lineage_store import LineageStore  # noqa: E402

ALLOWED_CAPABILITY_ID = "content_read"

# Enforce the allowlist at import time: this listener must never be able
# to invoke anything but content_read, regardless of what
# fabric.capabilities registers as an unrelated import side effect.
fi.CAPABILITIES.pop("echo_mock", None)
assert set(fi.CAPABILITIES) == {ALLOWED_CAPABILITY_ID}, (
    f"refusing to start: expected only {ALLOWED_CAPABILITY_ID!r} registered, found {sorted(fi.CAPABILITIES)}"
)


def _handle_artifact_envelope(payload: dict, node_id: str, local_transport: InMemoryFabricTransport) -> dict:
    for_node_id = payload.get("for_node_id")
    if for_node_id != node_id:
        return {"delivered": False, "reason": f"unknown node: this listener identifies as {node_id!r}, not {for_node_id!r}"}
    env, reason = wire.safe_envelope_from_wire(payload.get("envelope", {}))
    if env is None:
        return {"delivered": False, "reason": reason}
    return local_transport.deliver(node_id, env)


def _handle_capability_request(payload: dict, node_id: str, local_transport, lineage_store, artifact_index, replay_guard, integrity_key, key_store):
    request, reason = wire.safe_capability_request_from_wire(payload)
    if request is None:
        return None, reason
    if request.destination_node_id != node_id:
        result, receipt = fi._result_and_receipt(
            request, status=fi.CAP_FAILED, structured_result=None,
            error_detail=f"unknown node: this listener identifies as {node_id!r}, not {request.destination_node_id!r}",
        )
        return (result, receipt), None
    if request.capability_id != ALLOWED_CAPABILITY_ID:
        result, receipt = fi._result_and_receipt(
            request, status=fi.CAP_UNSUPPORTED, structured_result=None,
            error_detail=(
                f"capability {request.capability_id!r} is not in this listener's allowlist "
                f"({ALLOWED_CAPABILITY_ID!r} only)"
            ),
        )
        return (result, receipt), None
    result, receipt = fi.process_remote_capability_request(
        request, local_transport, lineage_store=lineage_store, artifact_index=artifact_index,
        replay_guard=replay_guard, integrity_key=integrity_key, key_store=key_store,
    )
    return (result, receipt), None


def run_server(host: str, port: int, authkey: bytes, node_id: str, lineage_dir: str,
               max_messages: int = 20, idle_timeout: float = 20.0,
               max_runtime_seconds: float = 120.0, max_message_bytes: int = 65536,
               integrity_key: Optional[bytes] = None, key_store_dir: Optional[str] = None) -> None:
    lineage_store = LineageStore(Path(lineage_dir))
    artifact_index = fi.FabricArtifactIndex()
    replay_guard = fi.RequestReplayGuard(Path(lineage_dir))
    key_store = fi.LocalKeyStore(Path(key_store_dir)) if key_store_dir else None
    local_transport = InMemoryFabricTransport(registered_nodes=(node_id,))

    listener = connection.Listener((host, port), family="AF_INET", authkey=authkey, backlog=1)
    bound_host, bound_port = listener.address
    print(f"PC_NODE_LISTENING {bound_host}:{bound_port}", flush=True)
    start = time.monotonic()
    try:
        conn = listener.accept()
    finally:
        listener.close()  # one-shot: never accepts a second connection

    print("PC_NODE_ACCEPTED", flush=True)
    handled = 0
    try:
        while handled < max_messages:
            elapsed = time.monotonic() - start
            if elapsed > max_runtime_seconds:
                print("PC_NODE_MAX_RUNTIME_EXCEEDED", flush=True)
                break
            kind, payload, error = wire.recv_message(
                conn, timeout=min(idle_timeout, max(0.0, max_runtime_seconds - elapsed)), max_bytes=max_message_bytes,
            )
            if error is not None:
                print(f"PC_NODE_RECV_ERROR {error}", flush=True)
                break
            handled += 1
            if kind == "SHUTDOWN":
                print("PC_NODE_SHUTDOWN_RECEIVED", flush=True)
                break
            elif kind == "ARTIFACT_ENVELOPE":
                outcome = _handle_artifact_envelope(payload, node_id, local_transport)
                wire.send_message(conn, "ARTIFACT_ENVELOPE_ACK", outcome)
                print(f"PC_NODE_ENVELOPE_RESULT {outcome}", flush=True)
            elif kind == "CAPABILITY_REQUEST":
                pair, framing_error = _handle_capability_request(
                    payload, node_id, local_transport, lineage_store, artifact_index, replay_guard, integrity_key, key_store,
                )
                if pair is None:
                    wire.send_message(conn, "CAPABILITY_RESPONSE_ERROR", {"reason": framing_error})
                    print(f"PC_NODE_CAPABILITY_FRAMING_ERROR {framing_error}", flush=True)
                else:
                    result, receipt = pair
                    wire.send_message(conn, "CAPABILITY_RESPONSE", wire.capability_response_to_wire(result, receipt))
                    print(
                        f"PC_NODE_CAPABILITY_RESULT status={result.status} receipt_id={receipt.receipt_id} "
                        f"artifact_id={receipt.artifact_id} sha256={receipt.sha256}",
                        flush=True,
                    )
            else:
                wire.send_message(conn, "PROTOCOL_ERROR", {"reason": f"unrecognized message kind {kind!r}"})
                print(f"PC_NODE_UNKNOWN_KIND {kind!r}", flush=True)
    finally:
        conn.close()
    print("PC_NODE_EXITING", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="ForgeWorld PC_NODE TCP fabric listener (bounded, one-shot, content_read only).")
    parser.add_argument("--host", required=True, help="LAN IP to bind, e.g. 192.168.1.85 -- never 0.0.0.0 or ::")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--authkey", required=True, help="hex-encoded shared secret; generate a fresh one per session, never reuse")
    parser.add_argument("--node-id", default="PC-NODE-MAIN")
    parser.add_argument("--lineage-dir", required=True)
    parser.add_argument("--max-messages", type=int, default=20)
    parser.add_argument("--idle-timeout", type=float, default=20.0)
    parser.add_argument("--max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--max-message-bytes", type=int, default=65536)
    parser.add_argument(
        "--integrity-key", default=None,
        help="hex-encoded HMAC key (MISSION: FW-MESSAGE-INTEGRITY-CONTRACT-001, legacy path). "
             "Ignored if --key-store-dir is also given. Test-only key material -- omit for no "
             "integrity verification (default, backward compatible).",
    )
    parser.add_argument(
        "--key-store-dir", default=None,
        help="directory for a LocalKeyStore (MISSION: FW-LOCAL-KEY-PROVISIONING-CONTRACT-001). "
             "Takes precedence over --integrity-key when given.",
    )
    args = parser.parse_args()

    if args.host in ("0.0.0.0", "::", ""):
        parser.error("refusing to bind to 0.0.0.0/::/empty -- pass the specific LAN IP to bind as narrowly as possible")

    run_server(
        host=args.host, port=args.port, authkey=bytes.fromhex(args.authkey),
        node_id=args.node_id, lineage_dir=args.lineage_dir,
        max_messages=args.max_messages, idle_timeout=args.idle_timeout,
        max_runtime_seconds=args.max_runtime_seconds, max_message_bytes=args.max_message_bytes,
        integrity_key=bytes.fromhex(args.integrity_key) if args.integrity_key else None,
        key_store_dir=args.key_store_dir,
    )


if __name__ == "__main__":
    main()
