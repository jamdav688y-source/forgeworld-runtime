"""Tests for FW-LOCAL-KEY-PROVISIONING-CONTRACT-001 (TCP transport half).

Same proof as fabric/tests/test_local_key_provisioning_loopback.py, over
the real AF_INET/TCP path instead. Binds ONLY to 127.0.0.1 on an
OS-assigned ephemeral port (--port 0); no LAN interface, no external
network.

Fixture code (_SpawnedTCPServer, _do_transfer) is duplicated from
fabric/tcp/tests/test_fabric_tcp.py's own fixtures, matching that file's
own precedent.
"""
import json
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
from fabric.loopback import wire
from fabric.loopback.transport import LoopbackClientTransport
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-KEYPROV-TCP"


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedTCPServer:
    """Duplicated from fabric/tcp/tests/test_fabric_tcp.py's fixture,
    extended with a key_store_dir passed as --key-store-dir. Binds ONLY
    to 127.0.0.1 on an OS-assigned ephemeral port."""

    def __init__(self, node_id="PC-NODE-KEYPROV-TCP", max_messages=20, idle_timeout=6.0,
                 max_runtime_seconds=30.0, max_message_bytes=65536, lineage_dir=None, key_store_dir=None):
        self.node_id = node_id
        self.authkey = os.urandom(16)
        self._owns_lineage_dir = lineage_dir is None
        self._lineage_tmp = tempfile.TemporaryDirectory() if lineage_dir is None else None
        self.lineage_dir = lineage_dir or self._lineage_tmp.name
        self._owns_key_store_dir = key_store_dir is None
        self._key_store_tmp = tempfile.TemporaryDirectory() if key_store_dir is None else None
        self.key_store_dir = key_store_dir or self._key_store_tmp.name
        self.host = "127.0.0.1"
        self.port = None
        self.proc = subprocess.Popen(
            [
                sys.executable, str(SERVER_SCRIPT),
                "--host", self.host, "--port", "0",  # 0 = OS-assigned ephemeral port
                "--authkey", self.authkey.hex(), "--node-id", self.node_id,
                "--lineage-dir", self.lineage_dir,
                "--key-store-dir", self.key_store_dir,
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


def _do_transfer(server, transport, payload=b"key-provisioning tcp probe payload",
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


def _signed_capability_request(server, env, correlation_id, transfer_result, key_id, key_bytes):
    unsigned = fi.RemoteCapabilityRequest(
        request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
        artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
        correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
    )
    return fi.sign_request(unsigned, key_bytes, key_id=key_id)


class TestActiveKeyOverTCP(unittest.TestCase):
    def test_active_key_signed_request_executes_and_secret_never_crosses_wire(self):
        server = _SpawnedTCPServer()
        try:
            operator_store = fi.LocalKeyStore(Path(server.key_store_dir))
            key_id = operator_store.provision_key()
            key_bytes = operator_store.resolve_key(key_id)

            transport = server.client_transport()
            payload = b"valid active-key tcp probe"
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result, key_id, key_bytes)

            wire_dict = wire.capability_request_to_wire(signed)
            wire_bytes = json.dumps(wire_dict).encode("utf-8")
            self.assertNotIn(key_bytes, wire_bytes)
            self.assertNotIn(key_bytes.hex().encode("ascii"), wire_bytes)

            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)
        finally:
            server.terminate()


class TestUnknownKeyOverTCP(unittest.TestCase):
    def test_unknown_key_id_rejected_with_zero_lineage_writes(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            fake_secret = fi.secrets.token_bytes(32)
            signed = _signed_capability_request(
                server, env, correlation_id, transfer_result, "IKEY-" + uuid.uuid4().hex, fake_secret,
            )
            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("integrity", result.error_detail.lower())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestRevokedKeyOverTCP(unittest.TestCase):
    def test_revoked_key_rejected_with_zero_lineage_writes(self):
        server = _SpawnedTCPServer()
        try:
            operator_store = fi.LocalKeyStore(Path(server.key_store_dir))
            key_id = operator_store.provision_key()
            key_bytes = operator_store.resolve_key(key_id)

            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result, key_id, key_bytes)

            operator_store.revoke_key(key_id, reason="test: simulate compromised key")

            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestRotationOverTCP(unittest.TestCase):
    def test_new_key_accepted_old_key_rejected_after_rotation(self):
        server = _SpawnedTCPServer()
        try:
            operator_store = fi.LocalKeyStore(Path(server.key_store_dir))
            k1 = operator_store.provision_key()
            k1_secret = operator_store.resolve_key(k1)

            transport = server.client_transport()
            env1, corr1, xfer1 = _do_transfer(server, transport, artifact_id=fi.ah_interface.new_artifact_id())
            old_key_request = _signed_capability_request(server, env1, corr1, xfer1, k1, k1_secret)

            k2 = operator_store.provision_key(supersedes=k1)  # hard cutover
            k2_secret = operator_store.resolve_key(k2)

            env2, corr2, xfer2 = _do_transfer(server, transport, artifact_id=fi.ah_interface.new_artifact_id())
            new_key_request = _signed_capability_request(server, env2, corr2, xfer2, k2, k2_secret)

            transport.send_capability_request(new_key_request)
            new_result, _, new_error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(new_error)
            self.assertEqual(new_result.status, fi.CAP_COMPLETED)

            transport.send_capability_request(old_key_request)
            old_result, _, old_error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(old_error)
            self.assertEqual(old_result.status, fi.CAP_FAILED)

            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)
        finally:
            server.terminate()


class TestProcessRestartKeyLifecycleOverTCP(unittest.TestCase):
    def test_revoked_key_remains_rejected_after_server_restart(self):
        shared_lineage_dir = tempfile.TemporaryDirectory()
        shared_key_store_dir = tempfile.TemporaryDirectory()
        try:
            operator_store = fi.LocalKeyStore(Path(shared_key_store_dir.name))
            key_id = operator_store.provision_key()
            key_bytes = operator_store.resolve_key(key_id)

            server1 = _SpawnedTCPServer(lineage_dir=shared_lineage_dir.name, key_store_dir=shared_key_store_dir.name)
            try:
                transport1 = server1.client_transport()
                env, corr, xfer = _do_transfer(server1, transport1)
                signed = _signed_capability_request(server1, env, corr, xfer, key_id, key_bytes)
                transport1.send_capability_request(signed)
                first, _, error1 = transport1.recv_capability_response(timeout=5)
                self.assertIsNone(error1)
                self.assertEqual(first.status, fi.CAP_COMPLETED)
                transport1.send_shutdown()
                transport1.close()
                server1.proc.wait(timeout=5)
            finally:
                server1.terminate()

            operator_store.revoke_key(key_id, reason="test: revoke between server restarts")

            server2 = _SpawnedTCPServer(
                node_id=server1.node_id, lineage_dir=shared_lineage_dir.name, key_store_dir=shared_key_store_dir.name,
            )
            try:
                transport2 = server2.client_transport()
                env2, corr2, xfer2 = _do_transfer(server2, transport2, artifact_id=fi.ah_interface.new_artifact_id())
                replay_with_revoked_key = _signed_capability_request(server2, env2, corr2, xfer2, key_id, key_bytes)
                transport2.send_capability_request(replay_with_revoked_key)
                second, _, error2 = transport2.recv_capability_response(timeout=5)
                self.assertIsNone(error2)
                self.assertEqual(second.status, fi.CAP_FAILED)

                lineage_store = LineageStore(Path(shared_lineage_dir.name))
                self.assertEqual(len(lineage_store.list_all()), 1)
            finally:
                server2.terminate()
        finally:
            shared_lineage_dir.cleanup()
            shared_key_store_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
