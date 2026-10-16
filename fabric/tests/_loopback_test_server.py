#!/usr/bin/env python3
"""TEST-ONLY loopback PC_NODE server (MISSION: FW-PHASE-1-HARDENING-001).

The production fabric/loopback/pc_node_server.py is governed-only and has no
test hooks. Loopback regression suites that need fault injection or the
older ungoverned modes start THIS script instead. It wraps the production
run_server() and passes the underscore-prefixed test parameters that the
production main() never passes:

  - TEST_HOOK "die" (process exits mid-request, no response) and
    "sleep_ms" (bounded slow-server simulation);
  - broken_incomplete_capability_for_testing (claims COMPLETED with no result);
  - _allow_ungoverned=True, so legacy integrity-key / key-store-only /
    no-store configurations can still be exercised end to end.

Never use this outside tests.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402
from fabric.loopback import pc_node_server, wire  # noqa: E402


class _AlwaysIncompleteTestCapability:
    """Claims COMPLETED but returns no structured_result, so the processor's
    incomplete-result detection can be proven across a process boundary."""

    capability_id = "broken_incomplete_capability_for_testing"

    def invoke(self, manifest_dict, payload):
        return fi.CAP_COMPLETED, None, None


def _test_hook(conn, payload):
    action = payload.get("action")
    if action == "die":
        os._exit(1)
    elif action == "sleep_ms":
        time.sleep(payload.get("ms", 0) / 1000.0)
        wire.send_message(conn, "TEST_HOOK_ACK", {})


def main() -> None:
    parser = argparse.ArgumentParser(description="TEST-ONLY loopback PC_NODE server.")
    parser.add_argument("--address", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--authkey", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--lineage-dir", required=True)
    parser.add_argument("--max-messages", type=int, default=100)
    parser.add_argument("--idle-timeout", type=float, default=15.0)
    parser.add_argument("--integrity-key", default=None)
    parser.add_argument("--key-store-dir", default=None)
    parser.add_argument("--pairing-store-dir", default=None)
    parser.add_argument("--peer-store-dir", default=None)
    parser.add_argument("--grant-store-dir", default=None)
    args = parser.parse_args()

    pc_node_server.run_server(
        address=args.address, family=args.family, authkey=bytes.fromhex(args.authkey),
        node_id=args.node_id, lineage_dir=args.lineage_dir,
        max_messages=args.max_messages, idle_timeout=args.idle_timeout,
        integrity_key=bytes.fromhex(args.integrity_key) if args.integrity_key else None,
        key_store_dir=args.key_store_dir, pairing_store_dir=args.pairing_store_dir,
        peer_store_dir=args.peer_store_dir, grant_store_dir=args.grant_store_dir,
        capability_ids=pc_node_server._KNOWN_CAPABILITY_IDS,
        _allow_ungoverned=True,
        _test_handlers={"TEST_HOOK": _test_hook},
        _test_capabilities=(_AlwaysIncompleteTestCapability(),),
    )


if __name__ == "__main__":
    main()
