"""TEST-ONLY governed identity for the TCP regression suites (MISSION:
FW-PHASE-1B-TCP-LOOPBACK-001).

fabric/tcp/pc_node_server.py is governed-only: it refuses to start without
key, pairing, peer and grant stores, and executes a request only for an
active pairing relationship, a bound peer, a valid integrity tag and an
operator-issued, expiring receiver-held grant. GovernedIdentity plays the
PC operator once per test server: confirmed relationship, bound peer, grant.

SigningClientTransport binds and signs any capability request that is not
already signed, so suites that build requests inline keep their assertions
unchanged. Requests a test signs itself (or deliberately leaves unsigned via
a raw send) are passed through untouched.
"""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fabric import interface as fi
from fabric.loopback.transport import LoopbackClientTransport

AUTHKEY_BYTES = fi.MIN_AUTHKEY_BYTES


def expiry_in(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(fi._TIMESTAMP_FORMAT)


class GovernedIdentity:
    def __init__(self, local_node_id: str, remote_node_id: str, capability_ids=("content_read",),
                 grant_ttl_seconds: float = 3600):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.dirs = {name: str(root / name) for name in ("keys", "pairing", "peers", "grants")}
        self.key_store = fi.LocalKeyStore(Path(self.dirs["keys"]))
        self.pairing_store = fi.PairingStore(Path(self.dirs["pairing"]))
        self.peer_store = fi.PeerIdentityStore(Path(self.dirs["peers"]))
        self.grant_store = fi.LocalGrantStore(Path(self.dirs["grants"]))
        self.local_node_id, self.remote_node_id = local_node_id, remote_node_id
        self.relationship = self.new_relationship(capability_ids, grant_ttl_seconds)

    def new_relationship(self, capability_ids=("content_read",), grant_ttl_seconds: float = 3600,
                         offer=None) -> dict:
        """Confirm a relationship (a fresh offer unless one is given), bind a
        new peer to it, and issue that peer an expiring grant."""
        if offer is None:
            offer = self.pairing_store.create_offer(self.local_node_id, self.remote_node_id, self.key_store)
        self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        peer_id = self.peer_store.register_peer()
        self.peer_store.bind_relationship(peer_id, offer["relationship_id"])
        grant_id = self.grant_store.issue_grant(
            peer_id, offer["relationship_id"], list(capability_ids), expiry_in(grant_ttl_seconds),
            issued_by="test_operator",
        )
        return {"offer": offer, "relationship_id": offer["relationship_id"], "key_id": offer["key_id"],
                "peer_id": peer_id, "grant_id": grant_id, "key_bytes": self.key_store.resolve_key(offer["key_id"])}

    def server_args(self) -> list:
        return ["--key-store-dir", self.dirs["keys"], "--pairing-store-dir", self.dirs["pairing"],
                "--peer-store-dir", self.dirs["peers"], "--grant-store-dir", self.dirs["grants"]]

    def bind_and_sign(self, request, relationship=None):
        rel = relationship or self.relationship
        bound = fi.replace(request, relationship_id=rel["relationship_id"], source_peer_id=rel["peer_id"])
        return fi.sign_request(bound, rel["key_bytes"], key_id=rel["key_id"])

    def cleanup(self):
        self._tmp.cleanup()


class SigningClientTransport(LoopbackClientTransport):
    def __init__(self, identity: GovernedIdentity, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._identity = identity

    def send_capability_request(self, request):
        if request.integrity_tag is None:
            request = self._identity.bind_and_sign(request)
        return super().send_capability_request(request)
