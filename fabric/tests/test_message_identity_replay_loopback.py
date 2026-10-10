"""Tests for FW-MESSAGE-IDENTITY-REPLAY-CONTRACT-001 (loopback transport
half).

Proves fabric.interface.RequestReplayGuard's at-most-once execution gate
survives a REAL process-boundary transport hop, exactly the way
fabric/tests/test_authority_expiry_loopback.py proved authority-expiry
enforcement does: a genuinely separate OS subprocess running
fabric/loopback/pc_node_server.py, now wired (this mission's smallest
production delta) to construct its own RequestReplayGuard over its
--lineage-dir and pass it into process_remote_capability_request().

Fixture code (_SpawnedServer, _do_transfer) is duplicated from
fabric/tests/test_fabric_loopback.py's fixtures rather than imported,
matching this repository's established convention (fabric/tcp/tests/
test_fabric_tcp.py already does the same). No existing test file is
modified.

Zero-re-execution evidence: the spawned server subprocess's own durable
LineageStore is the cross-process-observable proxy, exactly as in the
transport-proof mission -- a replayed request_id short-circuits inside
RequestReplayGuard BEFORE process_remote_capability_request() ever
reaches ah_interface.handoff() (which is what writes the lineage
record), so the lineage record count staying at 1 after two deliveries
of the same request_id is real, disk-based, cross-process proof that the
second delivery never reached the capability at all.
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
PHONE_ID = "PHONE-NODE-REPLAY-LOOPBACK"


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedServer:
    """Duplicated from fabric/tests/test_fabric_loopback.py's fixture of
    the same name (see module docstring). Accepts an externally supplied
    lineage_dir so TEST 9 can point a SECOND server instance at the SAME
    durable directory a first (now-terminated) server wrote to --
    modeling a real process restart with persisted state."""

    def __init__(self, node_id="PC-NODE-REPLAY-LOOPBACK", max_messages=100, idle_timeout=6.0, lineage_dir=None):
        self.node_id = node_id
        self.address, self.family = make_loopback_address(f"replay-test-{uuid.uuid4().hex[:8]}")
        self.authkey = os.urandom(16)
        self._owns_lineage_dir = lineage_dir is None
        self._tmp = tempfile.TemporaryDirectory() if lineage_dir is None else None
        self.lineage_dir = lineage_dir or self._tmp.name
        self.proc = None
        self._start(max_messages, idle_timeout)

    def _start(self, max_messages, idle_timeout):
        self.proc = subprocess.Popen(
            [
                sys.executable, str(SERVER_SCRIPT),
                "--address", self.address, "--family", self.family,
                "--authkey", self.authkey.hex(), "--node-id", self.node_id,
                "--lineage-dir", self.lineage_dir,
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
            self._tmp.cleanup()
        cleanup_loopback_address(self.address, self.family)


def _do_transfer(server, transport, payload=b"replay-contract loopback probe payload",
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


class TestDuplicateDeliveryOverLoopback(unittest.TestCase):
    """TEST 4."""

    def test_same_request_id_sent_twice_executes_at_most_once(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            payload = b"loopback replay probe payload"
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

            # Resend the IDENTICAL request (same request_id) over the SAME
            # connection -- a literal message replay.
            transport.send_capability_request(cap_request)
            second, receipt2, error2 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error2)
            self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
            self.assertEqual(second.structured_result, first.structured_result)

            lineage_store = LineageStore(Path(server.lineage_dir))
            records = lineage_store.list_all()
            self.assertEqual(len(records), 1)  # capability executed exactly once
        finally:
            server.terminate()


class TestProcessRestartPreservesReplayProtectionOverLoopback(unittest.TestCase):
    """TEST 9 -- a genuinely separate second OS subprocess, standing in
    for the first server having crashed/restarted, reads the SAME durable
    --lineage-dir a (now-terminated) first server wrote to."""

    def test_second_server_process_over_the_same_lineage_dir_recognizes_the_duplicate(self):
        shared_lineage_dir = tempfile.TemporaryDirectory()
        try:
            server1 = _SpawnedServer(lineage_dir=shared_lineage_dir.name)
            payload = b"process-restart replay probe payload"
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

            # A genuinely NEW OS process, a NEW RequestReplayGuard object,
            # constructed fresh from the SAME on-disk directory --
            # simulates the PC_NODE having restarted.
            server2 = _SpawnedServer(node_id=server1.node_id, lineage_dir=shared_lineage_dir.name)
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
                self.assertEqual(len(lineage_store.list_all()), 1)  # still exactly one execution, across two processes
            finally:
                server2.terminate()
        finally:
            shared_lineage_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
