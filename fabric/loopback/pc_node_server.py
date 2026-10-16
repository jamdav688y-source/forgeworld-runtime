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

GOVERNED ONLY (MISSION: FW-PHASE-1-HARDENING-001): this production entry
point refuses to start without --key-store-dir, --pairing-store-dir,
--peer-store-dir and --grant-store-dir, has no legacy --integrity-key mode,
requires an authkey of at least fabric.interface.MIN_AUTHKEY_BYTES, invokes
only the capabilities named by --capability, and bounds each message to
--max-message-bytes. It contains no test hooks: fault injection and the
deliberately broken test capability live in the test-only wrapper
fabric/tests/_loopback_test_server.py, which is the only caller of
run_server()'s underscore-prefixed parameters.
"""
from __future__ import annotations

import argparse
import sys
from multiprocessing import connection
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402
from fabric.transports import InMemoryFabricTransport  # noqa: E402
from fabric.loopback import wire  # noqa: E402
from fabric import capabilities as fabric_capabilities  # noqa: E402,F401 -- registers content_read/echo_mock/physical_ping
from artifact_handoff.lineage_store import LineageStore  # noqa: E402

DEFAULT_CAPABILITY_IDS = ("content_read",)
_KNOWN_CAPABILITY_IDS = ("content_read", "echo_mock", "physical_ping")
DEFAULT_MAX_MESSAGE_BYTES = 65536


def _enforce_capability_allowlist(allowed_capability_ids) -> None:
    """Removes every registered capability not in allowed_capability_ids from
    fi.CAPABILITIES, so this process can only ever invoke what it was
    started with -- whatever fabric.capabilities registers on import."""
    allowed = set(allowed_capability_ids)
    for capability_id in list(fi.CAPABILITIES):
        if capability_id not in allowed:
            fi.CAPABILITIES.pop(capability_id, None)
    if not set(fi.CAPABILITIES) <= allowed:
        raise fi.FabricError(f"refusing to start: unexpected capabilities registered {sorted(fi.CAPABILITIES)}")


def _handle_artifact_envelope(payload: dict, node_id: str, local_transport: InMemoryFabricTransport) -> dict:
    for_node_id = payload.get("for_node_id")
    if for_node_id != node_id:
        return {"delivered": False, "reason": f"unknown node: this listener identifies as {node_id!r}, not {for_node_id!r}"}
    env, reason = wire.safe_envelope_from_wire(payload.get("envelope", {}))
    if env is None:
        return {"delivered": False, "reason": reason}
    outcome = local_transport.deliver(node_id, env)
    return outcome


def _handle_capability_request(payload: dict, node_id: str, local_transport, lineage_store, artifact_index, replay_guard, integrity_key, key_store, pairing_store, peer_store, grant_store=None):
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
        replay_guard=replay_guard, integrity_key=integrity_key, key_store=key_store,
        pairing_store=pairing_store, peer_store=peer_store, grant_store=grant_store,
    )
    return (result, receipt), None


def run_server(address: str, family: str, authkey: bytes, node_id: str, lineage_dir: str,
               max_messages: int = 100, idle_timeout: float = 15.0, integrity_key: Optional[bytes] = None,
               key_store_dir: Optional[str] = None, pairing_store_dir: Optional[str] = None,
               peer_store_dir: Optional[str] = None, grant_store_dir: Optional[str] = None,
               capability_ids=DEFAULT_CAPABILITY_IDS, max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
               _allow_ungoverned: bool = False, _test_handlers: Optional[dict] = None,
               _test_capabilities=()) -> None:
    """Serve one connection. Refuses (FabricError) before listening unless
    the configuration is governed and the authkey is long enough. The
    underscore-prefixed parameters exist only for the test-only wrapper
    fabric/tests/_loopback_test_server.py; main() never passes them."""
    fi.require_minimum_authkey(authkey)
    if not _allow_ungoverned:
        fi.require_governed_configuration(
            key_store=key_store_dir, pairing_store=pairing_store_dir, peer_store=peer_store_dir,
            grant_store=grant_store_dir, integrity_key=integrity_key,
        )
    for provider in _test_capabilities:
        fi.register_capability(provider)
    _enforce_capability_allowlist(set(capability_ids) | {p.capability_id for p in _test_capabilities})
    test_handlers = dict(_test_handlers or {})

    lineage_store = LineageStore(Path(lineage_dir))
    artifact_index = fi.FabricArtifactIndex()
    replay_guard = fi.RequestReplayGuard(Path(lineage_dir))
    key_store = fi.LocalKeyStore(Path(key_store_dir)) if key_store_dir else None
    peer_store = fi.PeerIdentityStore(Path(peer_store_dir)) if peer_store_dir else None
    pairing_store = fi.PairingStore(Path(pairing_store_dir)) if pairing_store_dir else None
    grant_store = fi.LocalGrantStore(Path(grant_store_dir)) if grant_store_dir else None
    local_transport = InMemoryFabricTransport(registered_nodes=(node_id,))

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
            kind, payload, error = wire.recv_message(conn, timeout=idle_timeout, max_bytes=max_message_bytes)
            if error is not None:
                print(f"PC_NODE_RECV_ERROR {error}", flush=True)
                break
            handled += 1
            if kind == "SHUTDOWN":
                print("PC_NODE_SHUTDOWN_RECEIVED", flush=True)
                break
            elif kind in test_handlers:
                test_handlers[kind](conn, payload)
            elif kind == "ARTIFACT_ENVELOPE":
                outcome = _handle_artifact_envelope(payload, node_id, local_transport)
                wire.send_message(conn, "ARTIFACT_ENVELOPE_ACK", outcome)
            elif kind == "CAPABILITY_REQUEST":
                pair, framing_error = _handle_capability_request(
                    payload, node_id, local_transport, lineage_store, artifact_index, replay_guard,
                    integrity_key, key_store, pairing_store, peer_store, grant_store,
                )
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="ForgeWorld PC_NODE loopback listener (governed, bounded, one-shot).")
    parser.add_argument("--address", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--authkey", required=True,
                        help=f"hex-encoded shared secret, at least {fi.MIN_AUTHKEY_BYTES} bytes")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--lineage-dir", required=True)
    parser.add_argument("--max-messages", type=int, default=100)
    parser.add_argument("--idle-timeout", type=float, default=15.0)
    parser.add_argument("--max-message-bytes", type=int, default=DEFAULT_MAX_MESSAGE_BYTES)
    parser.add_argument("--key-store-dir", required=True, help="directory for a LocalKeyStore")
    parser.add_argument("--pairing-store-dir", required=True, help="directory for a PairingStore")
    parser.add_argument("--peer-store-dir", required=True, help="directory for a PeerIdentityStore")
    parser.add_argument(
        "--grant-store-dir", required=True,
        help="directory for a LocalGrantStore: execution needs an operator-issued grant for the peer "
             "and relationship (see pc_pairing_ceremony.py issue-grant)",
    )
    parser.add_argument(
        "--capability", action="append", choices=_KNOWN_CAPABILITY_IDS,
        help=f"capability this listener may invoke; repeatable (default: {', '.join(DEFAULT_CAPABILITY_IDS)})",
    )
    args = parser.parse_args(argv)
    try:
        authkey = bytes.fromhex(args.authkey)
        fi.require_minimum_authkey(authkey)
    except (ValueError, fi.FabricError) as exc:
        parser.error(f"invalid --authkey: {exc}")

    run_server(
        address=args.address, family=args.family, authkey=authkey,
        node_id=args.node_id, lineage_dir=args.lineage_dir,
        max_messages=args.max_messages, idle_timeout=args.idle_timeout,
        key_store_dir=args.key_store_dir, pairing_store_dir=args.pairing_store_dir,
        peer_store_dir=args.peer_store_dir, grant_store_dir=args.grant_store_dir,
        capability_ids=tuple(args.capability or DEFAULT_CAPABILITY_IDS),
        max_message_bytes=args.max_message_bytes,
    )


if __name__ == "__main__":
    main()
