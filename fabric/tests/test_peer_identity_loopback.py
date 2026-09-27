"""Tests for FW-PEER-IDENTITY-CONTRACT-001 (loopback transport half).

Proves fabric.interface.PeerIdentityStore's identity/binding lifecycle
survives a REAL process-boundary transport hop: a genuinely separate OS
subprocess running fabric/loopback/pc_node_server.py, started with
--peer-store-dir alongside --pairing-store-dir and --key-store-dir (this
mission's smallest production delta to that script), resolves
request.source_peer_id through its OWN PeerIdentityStore instance --
built fresh from the same on-disk directory the test process (acting as
the pairing/identity-registering "endpoint") writes to.

Fixture code (_SpawnedServer, _do_transfer) is duplicated from
fabric/tests/test_fabric_loopback.py's fixtures, matching this
repository's established convention. No existing test file is modified.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.loopback.transport import LoopbackClientTransport, make_loopback_address, cleanup_loopback_address
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "loopback" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-PEERID-LOOPBACK"


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedServer:
    """Duplicated from fabric/tests/test_fabric_loopback.py's fixture,
    extended with peer_store_dir/pairing_store_dir/key_store_dir passed
    as --peer-store-dir/--pairing-store-dir/--key-store-dir. Accepts
    externally supplied directories so a process-restart test can point
    a SECOND server instance at the SAME durable directories a first
    (now-terminated) server used."""

    def __init__(self, node_id="PC-NODE-PEERID-LOOPBACK", max_messages=100, idle_timeout=6.0,
                 lineage_dir=None, key_store_dir=None, pairing_store_dir=None, peer_store_dir=None):
        self.node_id = node_id
        self.address, self.family = make_loopback_address(f"peerid-test-{uuid.uuid4().hex[:8]}")
        self.authkey = os.urandom(16)
        self._owns_lineage_dir = lineage_dir is None
        self._lineage_tmp = tempfile.TemporaryDirectory() if lineage_dir is None else None
        self.lineage_dir = lineage_dir or self._lineage_tmp.name
        self._owns_key_store_dir = key_store_dir is None
        self._key_store_tmp = tempfile.TemporaryDirectory() if key_store_dir is None else None
        self.key_store_dir = key_store_dir or self._key_store_tmp.name
        self._owns_pairing_store_dir = pairing_store_dir is None
        self._pairing_store_tmp = tempfile.TemporaryDirectory() if pairing_store_dir is None else None
        self.pairing_store_dir = pairing_store_dir or self._pairing_store_tmp.name
        self._owns_peer_store_dir = peer_store_dir is None
        self._peer_store_tmp = tempfile.TemporaryDirectory() if peer_store_dir is None else None
        self.peer_store_dir = peer_store_dir or self._peer_store_tmp.name
        self.proc = None
        self._start(max_messages, idle_timeout)

    def _start(self, max_messages, idle_timeout):
        self.proc = subprocess.Popen(
            [
                sys.executable, str(SERVER_SCRIPT),
                "--address", self.address, "--family", self.family,
                "--authkey", self.authkey.hex(), "--node-id", self.node_id,
                "--lineage-dir", self.lineage_dir,
                "--key-store-dir", self.key_store_dir,
                "--pairing-store-dir", self.pairing_store_dir,
                "--peer-store-dir", self.peer_store_dir,
                "--max-messages", str(max_messages), "--idle-timeout", str(idle_timeout),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self._wait_for_listening()

    def _wait_for_listening(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited before listening: {self.proc.stderr.read()}")
            line = self.proc.stdout.readline()
            if line.startswith("PC_NODE_LISTENING"):
                return
        raise TimeoutError("server did not report PC_NODE_LISTENING in time")

    def client_transport(self, **kwargs) -> LoopbackClientTransport:
        return LoopbackClientTransport(self.address, self.family, self.authkey, **kwargs)

    def terminate(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.proc.stdout:
            self.proc.stdout.close()
        if self.proc.stderr:
            self.proc.stderr.close()
        if self._owns_lineage_dir:
            self._lineage_tmp.cleanup()
        if self._owns_key_store_dir:
            self._key_store_tmp.cleanup()
        if self._owns_pairing_store_dir:
            self._pairing_store_tmp.cleanup()
        if self._owns_peer_store_dir:
            self._peer_store_tmp.cleanup()
        cleanup_loopback_address(self.address, self.family)


def _do_transfer(server, transport, payload=b"peer identity loopback probe payload",
                  declared_content_type="text/plain", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type=declared_content_type, artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=server.node_id, authority_context=_authority("content_read"),
        correlation_id=correlation_id,
    )
    result = fi.submit_transfer(request, transport)
    return env, correlation_id, result


def _signed_capability_request(server, env, correlation_id, transfer_result, relationship, peer_id, key_bytes):
    unsigned = fi.RemoteCapabilityRequest(
        request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
        artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
        correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
        relationship_id=relationship["relationship_id"], source_peer_id=peer_id,
    )
    return fi.sign_request(unsigned, key_bytes, key_id=relationship["key_id"])


class TestFullChainOverLoopback(unittest.TestCase):
    def test_active_peer_bound_relationship_governs_a_request_end_to_end(self):
        server = _SpawnedServer()
        try:
            key_store = fi.LocalKeyStore(Path(server.key_store_dir))
            pairing_store = fi.PairingStore(Path(server.pairing_store_dir))
            peer_store = fi.PeerIdentityStore(Path(server.peer_store_dir))
            offer = pairing_store.create_offer(PHONE_ID, server.node_id, key_store)
            pairing_store.confirm(offer["relationship_id"], offer["sas"])
            peer_id = peer_store.register_peer()
            peer_store.bind_relationship(peer_id, offer["relationship_id"])
            key_bytes = key_store.resolve_key(offer["key_id"])

            transport = server.client_transport()
            payload = b"valid peer-identified loopback probe"
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result, offer, peer_id, key_bytes)

            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)
        finally:
            server.terminate()


class TestUnknownPeerOverLoopback(unittest.TestCase):
    def test_unknown_peer_id_rejected_with_zero_lineage_writes(self):
        server = _SpawnedServer()
        try:
            key_store = fi.LocalKeyStore(Path(server.key_store_dir))
            pairing_store = fi.PairingStore(Path(server.pairing_store_dir))
            offer = pairing_store.create_offer(PHONE_ID, server.node_id, key_store)
            pairing_store.confirm(offer["relationship_id"], offer["sas"])
            key_bytes = key_store.resolve_key(offer["key_id"])

            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            fake_peer_id = "PEER-" + uuid.uuid4().hex
            signed = _signed_capability_request(server, env, correlation_id, transfer_result, offer, fake_peer_id, key_bytes)

            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestRevokedPeerOverLoopback(unittest.TestCase):
    def test_revoked_peer_rejected_with_zero_lineage_writes(self):
        server = _SpawnedServer()
        try:
            key_store = fi.LocalKeyStore(Path(server.key_store_dir))
            pairing_store = fi.PairingStore(Path(server.pairing_store_dir))
            peer_store = fi.PeerIdentityStore(Path(server.peer_store_dir))
            offer = pairing_store.create_offer(PHONE_ID, server.node_id, key_store)
            pairing_store.confirm(offer["relationship_id"], offer["sas"])
            peer_id = peer_store.register_peer()
            peer_store.bind_relationship(peer_id, offer["relationship_id"])
            key_bytes = key_store.resolve_key(offer["key_id"])

            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result, offer, peer_id, key_bytes)

            peer_store.revoke_peer(peer_id, reason="test: simulate compromised peer")

            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestProcessRestartPeerIdentityLifecycleOverLoopback(unittest.TestCase):
    """A genuinely separate second OS subprocess, standing in for the
    first server having crashed/restarted, resolves peer identity
    lifecycle state from the SAME on-disk directories a (now-terminated)
    first server used."""

    def test_revoked_peer_remains_rejected_after_server_restart(self):
        shared_lineage_dir = tempfile.TemporaryDirectory()
        shared_key_store_dir = tempfile.TemporaryDirectory()
        shared_pairing_store_dir = tempfile.TemporaryDirectory()
        shared_peer_store_dir = tempfile.TemporaryDirectory()
        try:
            key_store = fi.LocalKeyStore(Path(shared_key_store_dir.name))
            pairing_store = fi.PairingStore(Path(shared_pairing_store_dir.name))
            peer_store = fi.PeerIdentityStore(Path(shared_peer_store_dir.name))
            offer = pairing_store.create_offer(PHONE_ID, "PC-NODE-PEERID-RESTART", key_store)
            pairing_store.confirm(offer["relationship_id"], offer["sas"])
            peer_id = peer_store.register_peer()
            peer_store.bind_relationship(peer_id, offer["relationship_id"])
            key_bytes = key_store.resolve_key(offer["key_id"])

            server1 = _SpawnedServer(
                node_id="PC-NODE-PEERID-RESTART", lineage_dir=shared_lineage_dir.name,
                key_store_dir=shared_key_store_dir.name, pairing_store_dir=shared_pairing_store_dir.name,
                peer_store_dir=shared_peer_store_dir.name,
            )
            try:
                transport1 = server1.client_transport()
                env, corr, xfer = _do_transfer(server1, transport1)
                signed = _signed_capability_request(server1, env, corr, xfer, offer, peer_id, key_bytes)
                transport1.send_capability_request(signed)
                first, _, error1 = transport1.recv_capability_response(timeout=5)
                self.assertIsNone(error1)
                self.assertEqual(first.status, fi.CAP_COMPLETED)
                transport1.send_shutdown()
                transport1.close()
                server1.proc.wait(timeout=5)
            finally:
                server1.terminate()

            peer_store.revoke_peer(peer_id, reason="test: revoke between server restarts")

            server2 = _SpawnedServer(
                node_id=server1.node_id, lineage_dir=shared_lineage_dir.name,
                key_store_dir=shared_key_store_dir.name, pairing_store_dir=shared_pairing_store_dir.name,
                peer_store_dir=shared_peer_store_dir.name,
            )
            try:
                transport2 = server2.client_transport()
                env2, corr2, xfer2 = _do_transfer(server2, transport2, artifact_id=fi.ah_interface.new_artifact_id())
                replay_with_revoked_peer = _signed_capability_request(server2, env2, corr2, xfer2, offer, peer_id, key_bytes)
                transport2.send_capability_request(replay_with_revoked_peer)
                second, _, error2 = transport2.recv_capability_response(timeout=5)
                self.assertIsNone(error2)
                self.assertEqual(second.status, fi.CAP_FAILED)

                lineage_store = LineageStore(Path(shared_lineage_dir.name))
                self.assertEqual(len(lineage_store.list_all()), 1)  # still only the first, pre-revocation execution
            finally:
                server2.terminate()
        finally:
            shared_lineage_dir.cleanup()
            shared_key_store_dir.cleanup()
            shared_pairing_store_dir.cleanup()
            shared_peer_store_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
