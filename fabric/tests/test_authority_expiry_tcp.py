"""Tests for FW-AUTHORITY-EXPIRY-TRANSPORT-PROOF-001 (TCP half).

Same governance proof as fabric/tests/test_authority_expiry_loopback.py,
over the real AF_INET/TCP path instead: a genuinely separate OS
subprocess running fabric/tcp/pc_node_server.py, bound to 127.0.0.1 on an
OS-assigned ephemeral port (--port 0), never 0.0.0.0/:: -- matching this
mission's localhost-only authorization and the existing
fabric/tcp/pc_node_server.py contract, which already refuses to bind
0.0.0.0/::/empty outright (see its own main()). No LAN interface is
bound; no external network is reached.

fabric/tcp/pc_node_server.py reuses fabric.loopback.wire and
fabric.interface.process_remote_capability_request() completely
unmodified (see that file's own docstring) -- the same authority gate
already proven at the primitive level, the in-process orchestration
level, and the loopback-transport level applies here identically. This
file exists to confirm that holds over a real TCP socket too, not to
reimplement it.

Fixture code (_SpawnedTCPServer, _do_transfer) is duplicated from
fabric/tcp/tests/test_fabric_tcp.py's own fixtures rather than imported,
matching that file's own precedent (it does not import
fabric/tests/test_fabric_loopback.py's fixture either). No existing test
file is modified.

Zero-execution evidence: identical technique to the loopback file --
the spawned server subprocess's own on-disk LineageStore is the
cross-process-observable proxy for "authority passed and handoff/invoke
were reached," since ah_interface.handoff() runs only after
authority_permits() succeeds and strictly before provider.invoke().
"""
import json
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
from fabric.loopback import wire
from fabric.loopback.transport import LoopbackClientTransport
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-EXPIRY-TCP"

PAST_EXPIRY = "2020-01-01T00:00:00Z"
FUTURE_EXPIRY = "2099-01-01T00:00:00Z"
MALFORMED_EXPIRY = "not-a-timestamp"


def _authority(capability_ids, expires_at=None, actor=PHONE_ID):
    return fi.AuthorityContext(
        actor_id=actor, granted_capability_ids=tuple(capability_ids),
        granted_by="test_policy", expires_at=expires_at,
    )


class _SpawnedTCPServer:
    """Duplicated from fabric/tcp/tests/test_fabric_tcp.py's fixture of
    the same name and behavior (see module docstring). Binds ONLY to
    127.0.0.1 on an OS-assigned ephemeral port (--port 0) -- no LAN
    interface, no external network, matching this mission's localhost-
    only transport authorization."""

    def __init__(self, node_id="PC-NODE-EXPIRY-TCP", max_messages=20, idle_timeout=6.0,
                 max_runtime_seconds=30.0, max_message_bytes=65536):
        self.node_id = node_id
        self.authkey = os.urandom(16)
        self._tmp = tempfile.TemporaryDirectory()
        self.lineage_dir = self._tmp.name
        self.host = "127.0.0.1"
        self.port = None
        self.proc = subprocess.Popen(
            [
                sys.executable, str(SERVER_SCRIPT),
                "--host", self.host, "--port", "0",  # 0 = OS-assigned ephemeral port
                "--authkey", self.authkey.hex(), "--node-id", self.node_id,
                "--lineage-dir", self.lineage_dir,
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
        self._tmp.cleanup()


def _do_transfer(server, transport, payload=b"authority-expiry tcp probe payload",
                  declared_content_type="text/plain", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type=declared_content_type, artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=server.node_id, authority_context=_authority(("content_read",)),
        correlation_id=correlation_id,
    )
    result = fi.submit_transfer(request, transport)
    return env, correlation_id, result


class TestExpiredAuthorityOverTCP(unittest.TestCase):
    def test_expired_authority_denied_with_zero_lineage_writes(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read",
                authority_context=_authority(("content_read",), expires_at=PAST_EXPIRY),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
            self.assertEqual(receipt.capability_status, fi.CAP_UNAUTHORIZED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestFutureAuthorityOverTCP(unittest.TestCase):
    def test_future_authority_permits_and_executes_exactly_once(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            payload = b"future-authority tcp probe payload"
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read",
                authority_context=_authority(("content_read",), expires_at=FUTURE_EXPIRY),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
            lineage_store = LineageStore(Path(server.lineage_dir))
            records = lineage_store.list_all()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["sha256"], env.sha256)
        finally:
            server.terminate()


class TestNoneExpiryOverTCP(unittest.TestCase):
    def test_non_expiring_authority_preserves_existing_execution(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            payload = b"non-expiring tcp probe payload"
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read",
                authority_context=_authority(("content_read",), expires_at=None),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
        finally:
            server.terminate()


class TestMalformedExpiryOverTCP(unittest.TestCase):
    def test_malformed_expiry_over_wire_fails_closed_with_zero_execution(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read",
                authority_context=_authority(("content_read",), expires_at=MALFORMED_EXPIRY),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


class TestExpiryDoesNotWeakenAllowlistOverTCP(unittest.TestCase):
    def test_future_expiry_does_not_bypass_capability_allowlist(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read",
                authority_context=_authority(("some_other_capability",), expires_at=FUTURE_EXPIRY),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 0)
        finally:
            server.terminate()


if __name__ == "__main__":
    unittest.main()
