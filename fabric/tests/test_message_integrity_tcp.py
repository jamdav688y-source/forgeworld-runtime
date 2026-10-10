"""Tests for FW-MESSAGE-INTEGRITY-CONTRACT-001 (TCP transport half).

Same proof as fabric/tests/test_message_integrity_loopback.py, over the
real AF_INET/TCP path instead. fabric/tcp/pc_node_server.py reuses
fi.process_remote_capability_request() and fi.verify_request_integrity()
completely unmodified from the loopback server's own usage (this
mission's production delta added the identical --integrity-key wiring to
both scripts).

Binds ONLY to 127.0.0.1 on an OS-assigned ephemeral port (--port 0);
no LAN interface, no external network.

Fixture code (_SpawnedTCPServer, _do_transfer) is duplicated from
fabric/tcp/tests/test_fabric_tcp.py's own fixtures, matching that file's
own precedent.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.loopback.transport import LoopbackClientTransport
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-INTEGRITY-TCP"
TEST_KEY = os.urandom(32)


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedTCPServer:
    """Duplicated from fabric/tcp/tests/test_fabric_tcp.py's fixture,
    extended with an integrity_key passed as --integrity-key. Binds ONLY
    to 127.0.0.1 on an OS-assigned ephemeral port."""

    def __init__(self, node_id="PC-NODE-INTEGRITY-TCP", max_messages=20, idle_timeout=6.0,
                 max_runtime_seconds=30.0, max_message_bytes=65536, integrity_key=TEST_KEY):
        self.node_id = node_id
        self.authkey = os.urandom(16)
        self._tmp = tempfile.TemporaryDirectory()
        self.lineage_dir = self._tmp.name
        self.host = "127.0.0.1"
        self.port = None
        args = [
            sys.executable, str(SERVER_SCRIPT),
            "--host", self.host, "--port", "0",  # 0 = OS-assigned ephemeral port
            "--authkey", self.authkey.hex(), "--node-id", self.node_id,
            "--lineage-dir", self.lineage_dir,
            "--max-messages", str(max_messages), "--idle-timeout", str(idle_timeout),
            "--max-runtime-seconds", str(max_runtime_seconds),
            "--max-message-bytes", str(max_message_bytes),
        ]
        if integrity_key is not None:
            args += ["--integrity-key", integrity_key.hex()]
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        self._tmp.cleanup()


def _do_transfer(server, transport, payload=b"integrity-contract tcp probe payload",
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


def _signed_capability_request(server, env, correlation_id, transfer_result, key=TEST_KEY):
    unsigned = fi.RemoteCapabilityRequest(
        request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
        artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
        correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
    )
    return fi.sign_request(unsigned, key) if key is not None else unsigned


class TestValidSignedRequestOverTCP(unittest.TestCase):
    def test_valid_signed_request_executes_once(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            payload = b"valid signed tcp probe"
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result)
            transport.send_capability_request(signed)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)
        finally:
            server.terminate()


class TestArtifactReferenceMutationOverTCP(unittest.TestCase):
    """capability_id mutation is NOT usable as the TCP adversarial probe
    here: fabric/tcp/pc_node_server.py's OWN pre-existing allowlist check
    (request.capability_id != ALLOWED_CAPABILITY_ID) runs OUTSIDE and
    BEFORE process_remote_capability_request() is ever called, so any
    capability_id other than "content_read" is intercepted as
    CAP_UNSUPPORTED by that separate mechanism before this mission's
    integrity check is ever reached -- a real, discovered ordering
    interaction (recorded in this mission's evidence receipt), not a
    security gap (both outcomes are zero-execution). artifact_id mutation
    is not subject to that pre-check and reaches integrity verification
    directly, proving the same invariant on a field this transport's own
    allowlist does not shadow."""

    def test_artifact_id_mutation_fails_integrity_with_zero_lineage_writes(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result)
            other_env = fi.build_artifact_envelope(PHONE_ID, b"a different tcp artifact entirely", declared_content_type="text/plain")
            tampered = fi.replace(signed, artifact_id=other_env.artifact_id)  # stale tag
            transport.send_capability_request(tampered)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("integrity", result.error_detail.lower())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestTagMutationOverTCP(unittest.TestCase):
    def test_flipped_tag_fails_integrity_with_zero_lineage_writes(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result)
            flipped_char = "0" if signed.integrity_tag[0] != "0" else "1"
            tampered = fi.replace(signed, integrity_tag=flipped_char + signed.integrity_tag[1:])
            transport.send_capability_request(tampered)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestMissingTagOverTCP(unittest.TestCase):
    def test_missing_tag_fails_when_server_requires_integrity(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            unsigned = _signed_capability_request(server, env, correlation_id, transfer_result, key=None)
            transport.send_capability_request(unsigned)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("integrity", result.error_detail.lower())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestCompletedRequestIdWithMutatedContentOverTCP(unittest.TestCase):
    def test_completed_request_id_replayed_with_mutated_artifact_reference_is_rejected(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result)
            transport.send_capability_request(signed)
            first, _, error1 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error1)
            self.assertEqual(first.status, fi.CAP_COMPLETED)

            other_env = fi.build_artifact_envelope(PHONE_ID, b"a different tcp artifact for the replay probe", declared_content_type="text/plain")
            tampered = fi.replace(signed, artifact_id=other_env.artifact_id)  # same request_id, mutated field, stale tag
            transport.send_capability_request(tampered)
            second, _, error2 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error2)
            self.assertEqual(second.status, fi.CAP_FAILED)
            self.assertNotEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)

            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)
        finally:
            server.terminate()


if __name__ == "__main__":
    unittest.main()
