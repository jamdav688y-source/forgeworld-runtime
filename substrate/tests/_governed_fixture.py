"""TEST-ONLY governed fabric fixture for substrate tests (MISSION:
FW-PHASE-1-HARDENING-001).

substrate.execute_workflow_step() now refuses to reach the fabric unless the
key, pairing, peer and grant stores are all supplied. This builds that
governed configuration once: a confirmed pairing relationship, a peer bound
to it, and an operator-issued, expiring grant for the given capabilities.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fabric import interface as fi


class GovernedFabric:
    def __init__(self, root: Path, local_node_id: str, remote_node_id: str, capability_ids=("physical_ping",)):
        root = Path(root)
        self.key_store = fi.LocalKeyStore(root / "keys")
        self.pairing_store = fi.PairingStore(root / "pairing")
        self.peer_store = fi.PeerIdentityStore(root / "peers")
        self.grant_store = fi.LocalGrantStore(root / "grants")
        offer = self.pairing_store.create_offer(local_node_id, remote_node_id, self.key_store)
        self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        self.relationship_id = offer["relationship_id"]
        self.key_id = offer["key_id"]
        self.peer_id = self.peer_store.register_peer()
        self.peer_store.bind_relationship(self.peer_id, self.relationship_id)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(fi._TIMESTAMP_FORMAT)
        self.grant_id = self.grant_store.issue_grant(
            self.peer_id, self.relationship_id, list(capability_ids), expires_at, issued_by="test_operator",
        )

    def sign(self, request: "fi.RemoteCapabilityRequest") -> "fi.RemoteCapabilityRequest":
        bound = fi.replace(request, relationship_id=self.relationship_id, source_peer_id=self.peer_id)
        return fi.sign_request(bound, self.key_store.resolve_key(self.key_id), key_id=self.key_id)

    def kwargs(self, **extra) -> dict:
        return dict(key_store=self.key_store, pairing_store=self.pairing_store,
                    peer_store=self.peer_store, grant_store=self.grant_store, **extra)
