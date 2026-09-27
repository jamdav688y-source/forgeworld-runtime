"""Tests for FW-MESSAGE-INTEGRITY-CONTRACT-001 (loopback transport half).

Proves fabric.interface's HMAC-SHA256 request-integrity gate survives a
REAL process-boundary transport hop: JSON serialization -> a real
multiprocessing.connection socket -> a genuinely separate OS subprocess
running fabric/loopback/pc_node_server.py, now started with
--integrity-key (this mission's smallest production delta to that
script) -> JSON deserialization -> the SAME unmodified
process_remote_capability_request(), which verifies integrity FIRST.

Fixture code (_SpawnedServer, _do_transfer) is duplicated from
fabric/tests/test_fabric_loopback.py's fixtures, matching this
repository's established convention. No existing test file is modified.

Zero-execution evidence: the server subprocess's own durable
LineageStore, exactly as in the authority-expiry and replay transport
proofs -- a request that fails integrity verification never reaches
ah_interface.handoff(), so the lineage record count staying at 0 (for a
rejected message) or exactly 1 (for the one valid execution) is real,
disk-based, cross-process proof.
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
PHONE_ID = "PHONE-NODE-INTEGRITY-LOOPBACK"
TEST_KEY = os.urandom(32)


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedServer:
    """Duplicated from fabric/tests/test_fabric_loopback.py's fixture,
    extended with an integrity_key passed as --integrity-key."""

    def __init__(self, node_id="PC-NODE-INTEGRITY-LOOPBACK", max_messages=100, idle_timeout=6.0, integrity_key=TEST_KEY):
        self.node_id = node_id
        self.address, self.family = make_loopback_address(f"integrity-test-{uuid.uuid4().hex[:8]}")
        self.authkey = os.urandom(16)
        self._tmp = tempfile.TemporaryDirectory()
        self.lineage_dir = self._tmp.name
        self.proc = None
        self._start(max_messages, idle_timeout, integrity_key)

    def _start(self, max_messages, idle_timeout, integrity_key):
        args = [
            sys.executable, str(SERVER_SCRIPT),
            "--address", self.address, "--family", self.family,
            "--authkey", self.authkey.hex(), "--node-id", self.node_id,
            "--lineage-dir", self.lineage_dir,
            "--max-messages", str(max_messages), "--idle-timeout", str(idle_timeout),
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
        self._tmp.cleanup()
        cleanup_loopback_address(self.address, self.family)


def _do_transfer(server, transport, payload=b"integrity-contract loopback probe payload",
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


class TestValidSignedRequestOverLoopback(unittest.TestCase):
    def test_valid_signed_request_executes_once(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            payload = b"valid signed loopback probe"
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


class TestCapabilityMutationOverLoopback(unittest.TestCase):
    def test_capability_mutation_fails_integrity_with_zero_lineage_writes(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result)
            tampered = fi.replace(signed, capability_id="echo_mock")  # stale tag
            transport.send_capability_request(tampered)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("integrity", result.error_detail.lower())
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestTagMutationOverLoopback(unittest.TestCase):
    def test_flipped_tag_fails_integrity_with_zero_lineage_writes(self):
        server = _SpawnedServer()
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


class TestMissingTagOverLoopback(unittest.TestCase):
    def test_missing_tag_fails_when_server_requires_integrity(self):
        server = _SpawnedServer()
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


class TestCompletedRequestIdWithMutatedContentOverLoopback(unittest.TestCase):
    """Section 12's critical case, over a real transport: an old trusted
    request_id carrying newly mutated content must be rejected as
    tampered, not answered with the historical duplicate disposition."""

    def test_completed_request_id_replayed_with_mutated_capability_is_rejected(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            signed = _signed_capability_request(server, env, correlation_id, transfer_result)
            transport.send_capability_request(signed)
            first, _, error1 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error1)
            self.assertEqual(first.status, fi.CAP_COMPLETED)

            tampered = fi.replace(signed, capability_id="echo_mock")  # same request_id, mutated field, stale tag
            transport.send_capability_request(tampered)
            second, _, error2 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error2)
            self.assertEqual(second.status, fi.CAP_FAILED)
            self.assertNotEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)

            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)  # still only the first, genuine execution
        finally:
            server.terminate()


if __name__ == "__main__":
    unittest.main()
