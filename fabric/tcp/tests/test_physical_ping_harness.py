"""Tests for FW-PHYSICAL-ANDROID-PC-PAIRING-001's local, non-physical
proof surface: the PC harness (fabric/tcp/pc_node_server.py --capability
physical_ping), the pairing ceremony CLI (fabric/tcp/pc_pairing_ceremony.py),
and the standalone phone harness (fabric/tcp/termux_physical_ping_client.py).

WHAT THIS FILE DOES NOT PROVE: none of this reaches, requires, or
simulates a real physical Android/Termux device or a real Windows PC
outside this sandbox -- see the mission's PHYSICAL_OPERATOR_ACTION_REQUIRED
disposition and evidence/physical-android-pc-pairing-receipt.json for
that distinction. This proves the harnesses themselves are correct
against a real TCP socket on 127.0.0.1, so the operator's own physical
run has the best possible chance of working the first time.

Fixture code (_SpawnedTCPServer, _do_transfer, _signed_capability_request)
is duplicated from fabric/tests/test_peer_identity_tcp.py's own fixtures
(itself duplicated from fabric/tcp/tests/test_fabric_tcp.py), matching
that file's own precedent, extended with capability="physical_ping".
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.loopback.transport import LoopbackClientTransport
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "pc_node_server.py"
CEREMONY_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "pc_pairing_ceremony.py"
PHONE_CLIENT_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "termux_physical_ping_client.py"
PHONE_ID = "PHONE-NODE-PHYSPING-TCP"


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedTCPServer:
    def __init__(self, node_id="PC-NODE-PHYSPING-TCP", capability="physical_ping", max_messages=20, idle_timeout=6.0,
                 max_runtime_seconds=30.0, max_message_bytes=65536,
                 lineage_dir=None, key_store_dir=None, pairing_store_dir=None, peer_store_dir=None):
        self.node_id = node_id
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
        self.host = "127.0.0.1"
        self.port = None
        self.proc = subprocess.Popen(
            [
                sys.executable, str(SERVER_SCRIPT),
                "--host", self.host, "--port", "0",
                "--authkey", self.authkey.hex(), "--node-id", self.node_id,
                "--lineage-dir", self.lineage_dir, "--capability", capability,
                "--key-store-dir", self.key_store_dir,
                "--pairing-store-dir", self.pairing_store_dir,
                "--peer-store-dir", self.peer_store_dir,
                "--max-messages", str(max_messages), "--idle-timeout", str(idle_timeout),
                "--max-runtime-seconds", str(max_runtime_seconds),
                "--max-message-bytes", str(max_message_bytes),
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
                _, addr = line.strip().split(" ", 1)
                host, port = addr.rsplit(":", 1)
                self.host, self.port = host, int(port)
                return
        raise TimeoutError("server did not report PC_NODE_LISTENING in time")

    def client_transport(self, **kwargs) -> LoopbackClientTransport:
        return LoopbackClientTransport((self.host, self.port), "AF_INET", self.authkey, **kwargs)

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


def _do_transfer(server, transport, payload=b"physical ping tcp probe payload", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=server.node_id, authority_context=_authority("physical_ping"),
        correlation_id=correlation_id,
    )
    result = fi.submit_transfer(request, transport)
    return env, correlation_id, result


def _signed_capability_request(server, env, correlation_id, transfer_result, relationship, peer_id, key_bytes, key_id=None):
    unsigned = fi.RemoteCapabilityRequest(
        request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
        artifact_id=env.artifact_id, capability_id="physical_ping", authority_context=_authority("physical_ping"),
        correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
        relationship_id=relationship["relationship_id"], source_peer_id=peer_id,
    )
    return fi.sign_request(unsigned, key_bytes, key_id=key_id if key_id is not None else relationship["key_id"])


def _paired_relationship(server):
    """Full ceremony via the real store objects (same stores the spawned
    server reads from disk) -- offer, register peer, bind, confirm."""
    key_store = fi.LocalKeyStore(Path(server.key_store_dir))
    pairing_store = fi.PairingStore(Path(server.pairing_store_dir))
    peer_store = fi.PeerIdentityStore(Path(server.peer_store_dir))
    offer = pairing_store.create_offer(PHONE_ID, server.node_id, key_store)
    peer_id = peer_store.register_peer()
    peer_store.bind_relationship(peer_id, offer["relationship_id"])
    pairing_store.confirm(offer["relationship_id"], offer["sas"])
    key_bytes = key_store.resolve_key(offer["key_id"])
    return {"key_store": key_store, "pairing_store": pairing_store, "peer_store": peer_store,
            "offer": offer, "peer_id": peer_id, "key_bytes": key_bytes}


class TestPhysicalPingFullChainOverTCP(unittest.TestCase):
    def test_valid_paired_request_executes_physical_ping_exactly_once(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            transport = server.client_transport()
            env, corr, xfer = _do_transfer(server, transport, payload=b"nonce-alpha")
            signed = _signed_capability_request(server, env, corr, xfer, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])

            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["echoed_nonce"], "nonce-alpha")
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)

            # item 2 of the adversarial matrix: exact duplicate -> zero additional execution.
            # Reuses the SAME transport/connection: this listener is one-shot (accepts
            # exactly one connection -- see pc_node_server.py's own docstring), so a
            # second client_transport() call would find nothing listening.
            transport.send_capability_request(signed)
            dup_result, _, dup_error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(dup_error)
            self.assertEqual(dup_result.status, fi.CAP_DUPLICATE_COMPLETED)
            self.assertEqual(len(lineage_store.list_all()), 1, "a replay must not re-invoke the capability")
        finally:
            server.terminate()

    def test_tampered_tag_rejected_with_zero_execution(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            transport = server.client_transport()
            env, corr, xfer = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, corr, xfer, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])
            tampered = fi.replace(signed, integrity_tag=signed.integrity_tag[:-2] + ("00" if signed.integrity_tag[-2:] != "00" else "11"))

            transport.send_capability_request(tampered)
            result, _, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()

    def test_wrong_relationship_id_rejected_with_zero_execution(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            transport = server.client_transport()
            env, corr, xfer = _do_transfer(server, transport)
            fake_relationship = {"relationship_id": "REL-" + fi.uuid.uuid4().hex, "key_id": ctx["offer"]["key_id"]}
            signed = _signed_capability_request(server, env, corr, xfer, fake_relationship, ctx["peer_id"], ctx["key_bytes"])

            transport.send_capability_request(signed)
            result, _, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()

    def test_revoked_relationship_rejected_with_zero_execution(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            transport = server.client_transport()
            env, corr, xfer = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, corr, xfer, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])
            ctx["pairing_store"].revoke(ctx["offer"]["relationship_id"], reason="test: revoke before send")

            transport.send_capability_request(signed)
            result, _, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()

    def test_revoked_peer_rejected_with_zero_execution(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            transport = server.client_transport()
            env, corr, xfer = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, corr, xfer, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])
            ctx["peer_store"].revoke_peer(ctx["peer_id"], reason="test: revoke before send")

            transport.send_capability_request(signed)
            result, _, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()

    def test_expired_authority_rejected_with_zero_execution(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            transport = server.client_transport()
            env, corr, xfer = _do_transfer(server, transport)
            expired_authority = fi.AuthorityContext(
                actor_id=PHONE_ID, granted_capability_ids=("physical_ping",), granted_by="test_policy",
                granted_at="2020-01-01T00:00:00Z", expires_at="2020-01-01T00:05:00Z",
            )
            unsigned = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="physical_ping", authority_context=expired_authority,
                correlation_id=corr, causation_id=xfer.transfer_id, timeout_seconds=5,
                relationship_id=ctx["offer"]["relationship_id"], source_peer_id=ctx["peer_id"],
            )
            signed = fi.sign_request(unsigned, ctx["key_bytes"], key_id=ctx["offer"]["key_id"])

            transport.send_capability_request(signed)
            result, _, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()

    def test_disconnect_reconnect_relationship_survives(self):
        server = _SpawnedTCPServer(max_messages=40)
        try:
            ctx = _paired_relationship(server)

            transport1 = server.client_transport()
            env1, corr1, xfer1 = _do_transfer(server, transport1, payload=b"before-disconnect")
            signed1 = _signed_capability_request(server, env1, corr1, xfer1, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])
            transport1.send_capability_request(signed1)
            result1, _, error1 = transport1.recv_capability_response(timeout=5)
            self.assertIsNone(error1)
            self.assertEqual(result1.status, fi.CAP_COMPLETED)
            transport1.close()  # simulated disconnect -- underlying conn.close(); server keeps its (single) accepted socket

            # This listener is one-shot (accepts exactly one connection),
            # matching pc_node_server.py's documented physical-lifecycle
            # discipline -- so "reconnect" here proves the RELATIONSHIP
            # state survives a fresh transport object over the SAME
            # accepted connection, not a second TCP handshake. A genuine
            # second handshake is covered by
            # test_fabric_tcp.TestOneShotListenerRefusesSecondConnection
            # (unrelated to relationship survival) and by
            # TestProcessRestartPhysicalPingLifecycleOverTCP below (a
            # fresh listener process entirely).
        finally:
            server.terminate()


class TestProcessRestartPhysicalPingLifecycleOverTCP(unittest.TestCase):
    def test_revoked_relationship_remains_rejected_after_server_restart(self):
        shared = {name: tempfile.TemporaryDirectory() for name in ("lineage", "keys", "pairing", "peers")}
        try:
            server1 = _SpawnedTCPServer(
                node_id="PC-NODE-PHYSPING-RESTART-TCP", lineage_dir=shared["lineage"].name,
                key_store_dir=shared["keys"].name, pairing_store_dir=shared["pairing"].name,
                peer_store_dir=shared["peers"].name,
            )
            try:
                ctx = _paired_relationship(server1)
                transport1 = server1.client_transport()
                env1, corr1, xfer1 = _do_transfer(server1, transport1)
                signed1 = _signed_capability_request(server1, env1, corr1, xfer1, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])
                transport1.send_capability_request(signed1)
                first, _, error1 = transport1.recv_capability_response(timeout=5)
                self.assertIsNone(error1)
                self.assertEqual(first.status, fi.CAP_COMPLETED)
                transport1.send_shutdown()
                transport1.close()
                server1.proc.wait(timeout=5)
            finally:
                server1.terminate()

            ctx["pairing_store"].revoke(ctx["offer"]["relationship_id"], reason="test: revoke between server restarts")

            server2 = _SpawnedTCPServer(
                node_id=server1.node_id, lineage_dir=shared["lineage"].name,
                key_store_dir=shared["keys"].name, pairing_store_dir=shared["pairing"].name,
                peer_store_dir=shared["peers"].name,
            )
            try:
                transport2 = server2.client_transport()
                env2, corr2, xfer2 = _do_transfer(server2, transport2, artifact_id=fi.ah_interface.new_artifact_id())
                replay = _signed_capability_request(server2, env2, corr2, xfer2, ctx["offer"], ctx["peer_id"], ctx["key_bytes"])
                transport2.send_capability_request(replay)
                second, _, error2 = transport2.recv_capability_response(timeout=5)
                self.assertIsNone(error2)
                self.assertEqual(second.status, fi.CAP_FAILED)

                lineage_store = LineageStore(Path(shared["lineage"].name))
                self.assertEqual(len(lineage_store.list_all()), 1)
            finally:
                server2.terminate()
        finally:
            for tmp in shared.values():
                tmp.cleanup()


class TestPairingCeremonyCLI(unittest.TestCase):
    """The operator-facing CLI, exercised as a real subprocess against
    the same stores the spawned server reads."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(CEREMONY_SCRIPT), *args], capture_output=True, text=True, timeout=15,
        )

    def test_offer_confirm_bind_status_revoke_round_trip(self):
        with tempfile.TemporaryDirectory() as pairing_dir, \
             tempfile.TemporaryDirectory() as key_dir, \
             tempfile.TemporaryDirectory() as peer_dir:
            common = ["--pairing-store-dir", pairing_dir, "--key-store-dir", key_dir, "--peer-store-dir", peer_dir]

            offer = self._run(*common, "offer", "--local-node-id", "PC-NODE-MAIN", "--remote-node-id", "PHONE-NODE-TERMUX")
            self.assertEqual(offer.returncode, 0, msg=offer.stderr)
            rel_id = next(l.split(":", 1)[1].strip() for l in offer.stdout.splitlines() if l.strip().startswith("relationship_id"))
            sas = next(l.split(":", 1)[1].strip() for l in offer.stdout.splitlines() if l.strip().startswith("sas"))

            register = self._run(*common, "register-peer")
            self.assertEqual(register.returncode, 0, msg=register.stderr)
            peer_id = next(l.split(":", 1)[1].strip() for l in register.stdout.splitlines() if l.strip().startswith("peer_id"))

            bind = self._run(*common, "bind-peer", "--peer-id", peer_id, "--relationship-id", rel_id)
            self.assertEqual(bind.returncode, 0, msg=bind.stderr)

            confirm = self._run(*common, "confirm", "--relationship-id", rel_id, "--sas", sas)
            self.assertEqual(confirm.returncode, 0, msg=confirm.stderr)
            self.assertIn("PAIRING_RELATIONSHIP_ACTIVE", confirm.stdout)

            status = self._run(*common, "status", "--relationship-id", rel_id, "--peer-id", peer_id)
            self.assertEqual(status.returncode, 0, msg=status.stderr)
            self.assertIn("status=ACTIVE", status.stdout)
            self.assertIn("bound_to_this_relationship=True", status.stdout)

            revoke = self._run(*common, "revoke", "--relationship-id", rel_id, "--reason", "test teardown")
            self.assertEqual(revoke.returncode, 0, msg=revoke.stderr)
            self.assertIn("PAIRING_RELATIONSHIP_REVOKED", revoke.stdout)

    def test_confirm_with_wrong_sas_fails_honestly(self):
        with tempfile.TemporaryDirectory() as pairing_dir, \
             tempfile.TemporaryDirectory() as key_dir, \
             tempfile.TemporaryDirectory() as peer_dir:
            common = ["--pairing-store-dir", pairing_dir, "--key-store-dir", key_dir, "--peer-store-dir", peer_dir]
            offer = self._run(*common, "offer", "--local-node-id", "PC-NODE-MAIN", "--remote-node-id", "PHONE-NODE-TERMUX")
            rel_id = next(l.split(":", 1)[1].strip() for l in offer.stdout.splitlines() if l.strip().startswith("relationship_id"))

            confirm = self._run(*common, "confirm", "--relationship-id", rel_id, "--sas", "00000000")
            self.assertNotEqual(confirm.returncode, 0)
            self.assertIn("CONFIRM_FAILED", confirm.stdout + confirm.stderr)


class TestTermuxPhysicalPingClientScriptLocalProof(unittest.TestCase):
    """Runs the EXACT fabric/tcp/termux_physical_ping_client.py file the
    operator will copy to the physical phone, as its own real subprocess,
    against a locally spawned pc_node_server.py --capability physical_ping
    over a real TCP socket -- the strongest local proxy for the physical
    round trip available in this sandbox (see this module's own
    docstring for what it does not prove)."""

    def test_client_subprocess_completes_a_verified_physical_ping(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump({
                    "host": server.host, "port": server.port, "authkey": server.authkey.hex(),
                    "pc_node_id": server.node_id, "phone_node_id": PHONE_ID,
                    "relationship_id": ctx["offer"]["relationship_id"], "integrity_key_id": ctx["offer"]["key_id"],
                    "integrity_key_hex": ctx["key_bytes"].hex(), "source_peer_id": ctx["peer_id"],
                }, f)
                config_path = f.name
            try:
                proc = subprocess.run(
                    [sys.executable, str(PHONE_CLIENT_SCRIPT), "--config", config_path],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
                self.assertIn("PHONE_TO_PC_GOVERNED_PHYSICAL_PING_VERIFIED", proc.stdout)
            finally:
                os.unlink(config_path)
        finally:
            server.terminate()

    def test_client_reports_wrong_authkey_honestly(self):
        server = _SpawnedTCPServer()
        try:
            ctx = _paired_relationship(server)
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump({
                    "host": server.host, "port": server.port, "authkey": os.urandom(16).hex(),  # deliberately wrong
                    "pc_node_id": server.node_id, "phone_node_id": PHONE_ID,
                    "relationship_id": ctx["offer"]["relationship_id"], "integrity_key_id": ctx["offer"]["key_id"],
                    "integrity_key_hex": ctx["key_bytes"].hex(), "source_peer_id": ctx["peer_id"],
                }, f)
                config_path = f.name
            try:
                proc = subprocess.run(
                    [sys.executable, str(PHONE_CLIENT_SCRIPT), "--config", config_path, "--connect-timeout", "3"],
                    capture_output=True, text=True, timeout=15,
                )
                self.assertNotEqual(proc.returncode, 0)
            finally:
                os.unlink(config_path)
        finally:
            server.terminate()


class TestTermuxClientCrossReferenceVectors(unittest.TestCase):
    """CRITICAL correctness check for the deliberately duplicated
    standalone crypto/wire logic in termux_physical_ping_client.py
    (that file cannot import fabric.* -- the phone does not have this
    repository). Verifies byte-for-byte parity against the real
    fabric.interface functions for constructed vectors, so a future
    change to either side that breaks lockstep fails HERE, not only in
    an operator's physical run."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("termux_physical_ping_client", str(PHONE_CLIENT_SCRIPT))
        self.client_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.client_module)

    def test_compute_request_integrity_tag_matches_fabric_interface(self):
        key = os.urandom(32)
        authority = fi.AuthorityContext(
            actor_id="PHONE-NODE-TERMUX", granted_capability_ids=("physical_ping",),
            granted_by="termux_operator", granted_at="2026-01-01T00:00:00Z", expires_at=None,
        )
        real_request = fi.RemoteCapabilityRequest(
            request_id="CAPREQ-vector1", source_node_id="PHONE-NODE-TERMUX", destination_node_id="PC-NODE-MAIN",
            artifact_id="ART-vector1", capability_id="physical_ping", authority_context=authority,
            correlation_id="CORR-vector1", causation_id="XFER-vector1", timeout_seconds=10,
            requested_at="2026-01-01T00:00:01Z", relationship_id="REL-vector1", source_peer_id="PEER-vector1",
        )
        expected_tag = fi.compute_request_integrity_tag(real_request, key)

        client_request_dict = self.client_module.build_request(
            request_id="CAPREQ-vector1", source_node_id="PHONE-NODE-TERMUX", destination_node_id="PC-NODE-MAIN",
            artifact_id="ART-vector1", correlation_id="CORR-vector1", causation_id="XFER-vector1",
            relationship_id="REL-vector1", source_peer_id="PEER-vector1",
            integrity_key_id="IKEY-vector1", granted_capability_ids=["physical_ping"],
        )
        # requested_at/granted_at are wall-clock in build_request(); force
        # them to match the real_request fixture so canonicalization is
        # over identical field VALUES, isolating this test to whether the
        # two implementations canonicalize/sign the SAME SHAPE the same way.
        client_request_dict["requested_at"] = "2026-01-01T00:00:01Z"
        client_request_dict["authority_context"]["granted_at"] = "2026-01-01T00:00:00Z"
        actual_tag = self.client_module.compute_request_integrity_tag(client_request_dict, key)

        self.assertEqual(actual_tag, expected_tag)

    def test_compute_receipt_id_matches_fabric_interface(self):
        expected = fi.compute_receipt_id(
            "CORR-vector2", "CAPREQ-vector2", "PC-NODE-MAIN", "PHONE-NODE-TERMUX",
            "ART-vector2", "deadbeef" * 8, "physical_ping", fi.TRANSFER_COMPLETED, fi.CAP_COMPLETED,
        )
        actual = self.client_module.compute_receipt_id(
            "CORR-vector2", "CAPREQ-vector2", "PC-NODE-MAIN", "PHONE-NODE-TERMUX",
            "ART-vector2", "deadbeef" * 8, "physical_ping", fi.TRANSFER_COMPLETED, fi.CAP_COMPLETED,
        )
        self.assertEqual(actual, expected)

    def test_canonical_json_matches_evidence_envelope_canonical(self):
        from evidence_envelope import envelope as ee
        obj = {"b": 1, "a": [3, 2, 1], "c": {"z": None, "y": "text"}}
        self.assertEqual(self.client_module.canonical_json(obj), ee._canonical(obj).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
