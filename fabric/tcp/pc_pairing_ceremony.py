#!/usr/bin/env python3
"""PC-side operator CLI for the physical pairing ceremony (MISSION:
FW-PHYSICAL-ANDROID-PC-PAIRING-001).

WHY THIS EXISTS: FW-LOCAL-PAIRING-KEY-ESTABLISHMENT-001 proved the
PairingStore/LocalKeyStore relationship-lifecycle bookkeeping, but every
one of its tests shared a single on-disk directory between "both sides"
-- an explicitly acknowledged proof-only shortcut (see PairingStore's own
module docstring in fabric/interface.py), not a physical pairing
solution. A real Android/Termux phone does not share this repository's
filesystem, so the secret key bytes PairingStore.create_offer() /
LocalKeyStore.provision_key() generate can only reach the phone through
an explicit OPERATOR action: read the hex off this screen, type it into
the phone harness's config once.

This script adds ZERO new trust logic. It is a thin operator-facing
wrapper around already-tested primitives:
  - fabric.interface.PairingStore   (create_offer / confirm / revoke)
  - fabric.interface.LocalKeyStore  (resolve_key -- to print the secret
    ONCE, at offer time, for out-of-band transcription)
  - fabric.interface.PeerIdentityStore (register_peer / bind_relationship
    / revoke_peer)

SECRET HANDLING: the secret is printed to stdout exactly once, by the
`offer` subcommand, with a loud warning. It is never written to a log
file, never included in the evidence receipt, and this script never
persists it anywhere the LocalKeyStore secrets directory does not
already (0o600, POSIX-permission-protected only -- see LocalKeyStore's
own STORAGE SECURITY LIMITATION docstring).

TYPICAL CEREMONY (see the mission's operator runbook for the full text):
  1. PC operator runs `register-peer` -- mints a peer_id representing
     the phone from the PC's point of view. Give this string to the
     phone (it goes verbatim into the phone harness's --source-peer-id).
  2. PC operator runs `offer` -- mints a relationship_id + key_id +
     secret + SAS. Give relationship_id, key_id, and the secret hex to
     the phone (its physical_ping client config). Read the SAS aloud (or
     compare on both screens) -- this is the human-verified out-of-band
     check that no third party substituted the offer in transit.
  3. PC operator runs `bind-peer` -- binds the peer_id from step 1 to
     the relationship_id from step 2 (PEER IDENTITY != PAIRING; both
     gates are enforced independently downstream).
  4. PC operator runs `confirm` with the SAS -- the relationship
     transitions PENDING_CONFIRMATION -> ACTIVE. Only after this does
     fabric.tcp.pc_node_server.py (started with --pairing-store-dir/
     --peer-store-dir/--key-store-dir pointed at the same directories)
     accept requests under this relationship_id.
  5. Revocation (`revoke` / `revoke-peer`) withdraws trust at either
     layer independently, at any later time.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402


def _stores(args):
    key_store = fi.LocalKeyStore(Path(args.key_store_dir))
    pairing_store = fi.PairingStore(Path(args.pairing_store_dir))
    peer_store = fi.PeerIdentityStore(Path(args.peer_store_dir)) if getattr(args, "peer_store_dir", None) else None
    return key_store, pairing_store, peer_store


def cmd_offer(args) -> int:
    key_store, pairing_store, _ = _stores(args)
    offer = pairing_store.create_offer(args.local_node_id, args.remote_node_id, key_store)
    secret = key_store.resolve_key(offer["key_id"])
    print("PAIRING_OFFER_CREATED (status=PENDING_CONFIRMATION -- grants nothing yet)")
    print(f"  relationship_id : {offer['relationship_id']}")
    print(f"  key_id          : {offer['key_id']}")
    print(f"  sas             : {offer['sas']}")
    print("  secret (hex)    : " + secret.hex())
    print("")
    print("!! Transcribe relationship_id, key_id, and the secret hex to the phone's")
    print("!! physical_ping client config NOW -- this is the ONLY time this script")
    print("!! prints the secret. Compare the sas value with the phone operator")
    print("!! out-of-band (read aloud / side-by-side) BEFORE running `confirm`.")
    return 0


def cmd_confirm(args) -> int:
    _, pairing_store, _ = _stores(args)
    try:
        pairing_store.confirm(args.relationship_id, args.sas)
    except fi.PairingConflictError as exc:
        print(f"CONFIRM_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PAIRING_RELATIONSHIP_ACTIVE relationship_id={args.relationship_id}")
    return 0


def cmd_revoke(args) -> int:
    _, pairing_store, _ = _stores(args)
    try:
        pairing_store.revoke(args.relationship_id, reason=args.reason or "")
    except fi.PairingConflictError as exc:
        print(f"REVOKE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PAIRING_RELATIONSHIP_REVOKED relationship_id={args.relationship_id}")
    return 0


def cmd_status(args) -> int:
    _, pairing_store, peer_store = _stores(args)
    print(f"relationship_id={args.relationship_id} status={pairing_store.status_of(args.relationship_id)}")
    if args.peer_id and peer_store is not None:
        print(f"peer_id={args.peer_id} status={peer_store.status_of(args.peer_id)}")
        print(f"bound_to_this_relationship={peer_store.is_relationship_bound_to_peer(args.peer_id, args.relationship_id)}")
    return 0


def cmd_register_peer(args) -> int:
    _, _, peer_store = _stores(args)
    peer_id = peer_store.register_peer()
    print("PEER_REGISTERED (status=ACTIVE, not yet bound to any relationship)")
    print(f"  peer_id : {peer_id}")
    print("")
    print("!! Give this peer_id to the phone verbatim -- it goes into the phone")
    print("!! harness's --source-peer-id. It is NOT secret, but it is also not a")
    print("!! human name/device label; it names only this PairingRelationship's")
    print("!! counterparty from the PC's point of view.")
    return 0


def cmd_bind_peer(args) -> int:
    _, _, peer_store = _stores(args)
    try:
        peer_store.bind_relationship(args.peer_id, args.relationship_id)
    except fi.PeerIdentityConflictError as exc:
        print(f"BIND_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PEER_BOUND peer_id={args.peer_id} relationship_id={args.relationship_id}")
    return 0


def cmd_revoke_peer(args) -> int:
    _, _, peer_store = _stores(args)
    try:
        peer_store.revoke_peer(args.peer_id, reason=args.reason or "")
    except fi.PeerIdentityConflictError as exc:
        print(f"REVOKE_PEER_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PEER_REVOKED peer_id={args.peer_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ForgeWorld PC-side physical pairing ceremony CLI.")
    parser.add_argument("--pairing-store-dir", required=True)
    parser.add_argument("--key-store-dir", required=True)
    parser.add_argument("--peer-store-dir", default=None, help="required by register-peer/bind-peer/revoke-peer/status --peer-id")
    sub = parser.add_subparsers(dest="command", required=True)

    p_offer = sub.add_parser("offer", help="create a new PENDING_CONFIRMATION relationship + fresh key")
    p_offer.add_argument("--local-node-id", required=True, help="this PC's node_id, e.g. PC-NODE-MAIN")
    p_offer.add_argument("--remote-node-id", required=True, help="the phone's node_id, e.g. PHONE-NODE-TERMUX")
    p_offer.set_defaults(func=cmd_offer)

    p_confirm = sub.add_parser("confirm", help="activate a relationship after out-of-band SAS verification")
    p_confirm.add_argument("--relationship-id", required=True)
    p_confirm.add_argument("--sas", required=True)
    p_confirm.set_defaults(func=cmd_confirm)

    p_revoke = sub.add_parser("revoke", help="revoke a relationship (idempotent)")
    p_revoke.add_argument("--relationship-id", required=True)
    p_revoke.add_argument("--reason", default="")
    p_revoke.set_defaults(func=cmd_revoke)

    p_status = sub.add_parser("status", help="show current relationship (and optionally peer) status")
    p_status.add_argument("--relationship-id", required=True)
    p_status.add_argument("--peer-id", default=None)
    p_status.set_defaults(func=cmd_status)

    p_reg = sub.add_parser("register-peer", help="mint a fresh ACTIVE peer_id representing the phone")
    p_reg.set_defaults(func=cmd_register_peer)

    p_bind = sub.add_parser("bind-peer", help="bind an existing peer_id to a relationship_id")
    p_bind.add_argument("--peer-id", required=True)
    p_bind.add_argument("--relationship-id", required=True)
    p_bind.set_defaults(func=cmd_bind_peer)

    p_revoke_peer = sub.add_parser("revoke-peer", help="revoke a peer_id (idempotent)")
    p_revoke_peer.add_argument("--peer-id", required=True)
    p_revoke_peer.add_argument("--reason", default="")
    p_revoke_peer.set_defaults(func=cmd_revoke_peer)

    args = parser.parse_args()
    if args.command in ("register-peer", "bind-peer", "revoke-peer") and not args.peer_store_dir:
        parser.error(f"--peer-store-dir is required for '{args.command}'")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
