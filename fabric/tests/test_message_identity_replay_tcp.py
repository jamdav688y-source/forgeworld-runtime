"""Tests for FW-MESSAGE-IDENTITY-REPLAY-CONTRACT-001 (TCP transport half).

Same proof as fabric/tests/test_message_identity_replay_loopback.py, over
the real AF_INET/TCP path instead. fabric/tcp/pc_node_server.py reuses
fi.process_remote_capability_request() and fi.RequestReplayGuard
completely unmodified from the loopback server's own usage (this
mission's production delta added the identical one-line wiring to both
scripts) -- this file exists to confirm that holds over a real TCP
socket too, not to reimplement it.

Binds ONLY to 127.0.0.1 on an OS-assigned ephemeral port (--port 0),
matching this mission's localhost-only transport authorization; no LAN
interface, no external network.

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
PHONE_ID = "PHONE-NODE-REPLAY-TCP"


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedTCPServer:
    """Duplicated from fabric/tcp/tests/test_fabric_tcp.py's fixture of
    the same name. Accepts an externally supplied lineage_dir so the
    process-restart test can point a SECOND server instance at the SAME
    durable directory a first (now-terminated) server wrote to. Binds
    ONLY to 127.0.0.1 on an OS-assigned ephemeral port."""

    def __init__(self, node_id="PC-NODE-REPLAY-TCP", max_messages=20, idle_timeout=6.0,
                 max_runtime_seconds=30.0, max_message_bytes=65536, lineage_dir=None):
        self.node_id = node_id
        self.authkey = os.urandom(16)
        self._owns_lineage_dir = lineage_dir is None
        self._tmp = tempfile.TemporaryDirectory() if lineage_dir is None else None
        self.lineage_dir = lineage_dir or self._tmp.name
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
        if self._owns_lineage_dir:
            self._tmp.cleanup()


def _do_transfer(server, transport, payload=b"replay-contract tcp probe payload",
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


class TestDuplicateDeliveryOverTCP(unittest.TestCase):
    """TEST 5."""

    def test_same_request_id_sent_twice_executes_at_most_once(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            payload = b"tcp replay probe payload"
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            first, receipt1, error1 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error1)
            self.assertEqual(first.status, fi.CAP_COMPLETED)
            self.assertEqual(first.structured_result["text_content"], payload.decode())

            transport.send_capability_request(cap_request)
            second, receipt2, error2 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error2)
            self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
            self.assertEqual(second.structured_result, first.structured_result)

            lineage_store = LineageStore(Path(server.lineage_dir))
            self.assertEqual(len(lineage_store.list_all()), 1)
        finally:
            server.terminate()


class TestProcessRestartPreservesReplayProtectionOverTCP(unittest.TestCase):
    """TEST 9, TCP transport."""

    def test_second_server_process_over_the_same_lineage_dir_recognizes_the_duplicate(self):
        shared_lineage_dir = tempfile.TemporaryDirectory()
        try:
            server1 = _SpawnedTCPServer(lineage_dir=shared_lineage_dir.name)
            payload = b"tcp process-restart replay probe payload"
            try:
                transport1 = server1.client_transport()
                env, correlation_id, transfer_result = _do_transfer(server1, transport1, payload=payload)
                cap_request = fi.RemoteCapabilityRequest(
                    request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server1.node_id,
                    artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                    correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
                )
                transport1.send_capability_request(cap_request)
                first, _, error1 = transport1.recv_capability_response(timeout=5)
                self.assertIsNone(error1)
                self.assertEqual(first.status, fi.CAP_COMPLETED)
                transport1.send_shutdown()
                transport1.close()
                server1.proc.wait(timeout=5)
            finally:
                server1.terminate()

            server2 = _SpawnedTCPServer(node_id=server1.node_id, lineage_dir=shared_lineage_dir.name)
            try:
                transport2 = server2.client_transport()
                replay_request = fi.RemoteCapabilityRequest(
                    request_id=cap_request.request_id, source_node_id=cap_request.source_node_id,
                    destination_node_id=server2.node_id, artifact_id=cap_request.artifact_id,
                    capability_id=cap_request.capability_id, authority_context=cap_request.authority_context,
                    correlation_id=cap_request.correlation_id, causation_id=cap_request.causation_id,
                    timeout_seconds=cap_request.timeout_seconds,
                )
                transport2.send_capability_request(replay_request)
                second, _, error2 = transport2.recv_capability_response(timeout=5)
                self.assertIsNone(error2)
                self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
                self.assertEqual(second.structured_result["text_content"], payload.decode())

                lineage_store = LineageStore(Path(shared_lineage_dir.name))
                self.assertEqual(len(lineage_store.list_all()), 1)
            finally:
                server2.terminate()
        finally:
            shared_lineage_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
