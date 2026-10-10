"""Tests for FW-FABRIC-TRANSPORT-LOOPBACK-001.

Stdlib `unittest`. Every test either spawns fabric/loopback/pc_node_server.py
as a genuinely separate OS process (subprocess.Popen) or exercises
fabric.loopback.wire's framing directly over a multiprocessing.connection.Pipe
(also two real endpoints, no subprocess needed for the pure framing checks).
No network beyond loopback, no phone, no Ollama, no model, no external
API, no cloud service, no LinkedIn access, no OpenClaw, no Hermes, no
SSH, no new long-lived service is created anywhere in this file.
"""
import base64
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from multiprocessing import connection as mp_connection
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.loopback import wire
from fabric.loopback.transport import LoopbackClientTransport, make_loopback_address, cleanup_loopback_address, verify_capability_response
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "loopback" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-LOOPBACK"


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedServer:
    """Wraps a real subprocess running pc_node_server.py. Bounded:
    max_messages caps how long it will run, idle_timeout bounds how long
    it waits for the next message before giving up on its own."""

    def __init__(self, node_id="PC-NODE-LOOPBACK", max_messages=100, idle_timeout=6.0):
        self.node_id = node_id
        self.address, self.family = make_loopback_address(f"test-{uuid.uuid4().hex[:8]}")
        self.authkey = os.urandom(16)
        self._tmp = tempfile.TemporaryDirectory()
        self.lineage_dir = self._tmp.name
        self.proc = None
        self._start(max_messages, idle_timeout)

    def _start(self, max_messages, idle_timeout):
        import subprocess
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
        self._tmp.cleanup()
        cleanup_loopback_address(self.address, self.family)


def _do_transfer(server: _SpawnedServer, transport, payload=b"synthetic harvested observation text",
                  declared_content_type="text/plain", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type=declared_content_type, artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=server.node_id, authority_context=_authority("content_read"), correlation_id=correlation_id,
    )
    result = fi.submit_transfer(request, transport)
    return env, correlation_id, result


class TestWireFramingFailureModes(unittest.TestCase):
    """malformed serialized message / truncated message / timeout, proven
    directly at the framing layer over a real pipe -- no subprocess
    needed to exercise this specific boundary."""

    def test_malformed_json_is_reported_honestly(self):
        a, b = mp_connection.Pipe()
        try:
            a.send_bytes(b"not json at all {{{")
            kind, payload, error = wire.recv_message(b, timeout=2)
            self.assertIsNone(kind)
            self.assertIn("MALFORMED", error)
        finally:
            a.close(); b.close()

    def test_truncated_json_is_reported_honestly(self):
        a, b = mp_connection.Pipe()
        try:
            a.send_bytes(b'{"kind": "ARTIFACT_ENVELOPE", "payload": {"envelope_id": "ENV-x"')
            kind, payload, error = wire.recv_message(b, timeout=2)
            self.assertIsNone(kind)
            self.assertIn("MALFORMED", error)
        finally:
            a.close(); b.close()

    def test_missing_kind_or_payload_structure_is_malformed(self):
        a, b = mp_connection.Pipe()
        try:
            a.send_bytes(json.dumps({"nope": "not the expected envelope shape"}).encode())
            kind, payload, error = wire.recv_message(b, timeout=2)
            self.assertIsNone(kind)
            self.assertIn("MALFORMED", error)
        finally:
            a.close(); b.close()

    def test_timeout_when_nothing_sent(self):
        a, b = mp_connection.Pipe()
        try:
            start = time.monotonic()
            kind, payload, error = wire.recv_message(b, timeout=0.3)
            elapsed = time.monotonic() - start
            self.assertIsNone(kind)
            self.assertIn("TIMEOUT", error)
            self.assertGreaterEqual(elapsed, 0.25)
        finally:
            a.close(); b.close()

    def test_eof_when_sender_closed(self):
        a, b = mp_connection.Pipe()
        a.close()
        try:
            kind, payload, error = wire.recv_message(b, timeout=2)
            self.assertIsNone(kind)
            self.assertIn("EOF", error)
        finally:
            b.close()


class TestDestinationProcessAbsent(unittest.TestCase):
    def test_no_listener_is_reported_unreachable(self):
        address, family = make_loopback_address("nobody-home")
        try:
            transport = LoopbackClientTransport(address, family, os.urandom(16), connect_timeout=1.0)
            env = fi.build_artifact_envelope(PHONE_ID, b"x", declared_content_type="text/plain")
            request = fi.TransferRequest(
                request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
                destination_node_id="PC-NODE-LOOPBACK", authority_context=_authority("content_read"),
                correlation_id=fi._new_id("CORR"),
            )
            result = fi.submit_transfer(request, transport)
            self.assertEqual(result.transfer_state, fi.TRANSFER_UNREACHABLE)
            self.assertIn("not reachable", result.error_detail)
        finally:
            cleanup_loopback_address(address, family)


class TestFullTwoProcessRoundTrip(unittest.TestCase):
    """The mission's required proof trace, across a REAL process
    boundary: PHONE (this test process) <-> PC (a spawned subprocess)."""

    def test_phone_to_pc_to_phone_across_real_process_boundary(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            payload = b"Observed note: prospective contact mentioned a hiring need."
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)

            self.assertEqual(transfer_result.transfer_state, fi.TRANSFER_COMPLETED)
            self.assertTrue(transfer_result.integrity_verified)
            self.assertEqual(transfer_result.trust_status, fi.TRUST_STATUS)
            self.assertEqual(transfer_result.possession_status, fi.POSSESSION_STATUS)

            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            send_error = transport.send_capability_request(cap_request)
            self.assertIsNone(send_error)
            result, receipt, recv_error = transport.recv_capability_response(timeout=10)
            self.assertIsNone(recv_error, recv_error)

            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
            self.assertEqual(result.evidence_status, "NOT_EVIDENCE")
            self.assertEqual(result.promotion_status, "NOT_PROMOTED")
            self.assertEqual(receipt.truth_status, "RECEIPT_NOT_TRUTH")

            # PHONE_NODE independently verifies correlation/causation and
            # recomputes the receipt id -- transport != trust.
            verification_error = verify_capability_response(cap_request, result, receipt)
            self.assertIsNone(verification_error, verification_error)

            # PC_NODE genuinely preserved provenance in a REAL separate
            # process's own filesystem writes -- read it back independently.
            lineage_store = LineageStore(Path(server.lineage_dir))
            records = lineage_store.list_all()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["sha256"], env.sha256)
            self.assertEqual(records[0]["detected_content_type"], "text/plain")

            transport.send_shutdown()
            transport.close()
            server.proc.wait(timeout=5)
            self.assertEqual(server.proc.returncode, 0)
        finally:
            server.terminate()


class TestUnknownNodeOverWire(unittest.TestCase):
    def test_capability_request_addressed_to_wrong_node_is_rejected(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            wrong_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id="SOME-OTHER-PC-NODE",
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(wrong_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("unknown node", result.error_detail)
        finally:
            server.terminate()


class TestUnsupportedCapabilityOverWire(unittest.TestCase):
    def test_unregistered_capability_id_is_unsupported(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="translate_klingon",
                authority_context=_authority("translate_klingon"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNSUPPORTED)
        finally:
            server.terminate()


class TestUnauthorizedOverWire(unittest.TestCase):
    def test_capability_not_in_granted_scope_is_unauthorized(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority(),  # empty grant
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        finally:
            server.terminate()


class TestDuplicateArtifactOverWire(unittest.TestCase):
    def test_same_artifact_id_different_content_is_a_conflict_within_one_server_session(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            shared_id = fi.ah_interface.new_artifact_id()

            env1, corr1, xfer1 = _do_transfer(server, transport, payload=b"first version", artifact_id=shared_id)
            req1 = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env1.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=corr1, causation_id=xfer1.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(req1)
            result1, _, error1 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error1)
            self.assertEqual(result1.status, fi.CAP_COMPLETED)

            env2, corr2, xfer2 = _do_transfer(server, transport, payload=b"a DIFFERENT version, same artifact_id", artifact_id=shared_id)
            req2 = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env2.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=corr2, causation_id=xfer2.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(req2)
            result2, _, error2 = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error2)
            self.assertEqual(result2.status, fi.CAP_DUPLICATE_CONFLICT)
        finally:
            server.terminate()


class TestHashMismatchOverWire(unittest.TestCase):
    def test_in_transit_corruption_is_caught_by_pc_independent_reverification(self):
        """Delivery itself (InMemoryFabricTransport.deliver) does not
        validate -- PC's own independent hash check happens when
        process_remote_capability_request() pulls and re-validates the
        envelope, exactly as it already does in-process. This proves
        that check survives a real wire hop, including corruption the
        SENDER's own (already-correct) hash did not and could not catch."""
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env = fi.build_artifact_envelope(PHONE_ID, b"authentic payload data", declared_content_type="text/plain")
            conn = transport._raw_connection_for_testing()

            wire_env = wire.envelope_to_wire(env)
            corrupted = dict(wire_env)
            # Same length as the original (so the SIZE check still passes)
            # but every byte flipped (so the content, and therefore its
            # hash, is definitely different) -- isolates the sha256
            # mismatch check specifically, rather than tripping the
            # separate size-mismatch check first.
            flipped = bytes(b ^ 0xFF for b in env.payload)
            corrupted["payload_b64"] = base64.b64encode(flipped).decode()
            wire.send_message(conn, "ARTIFACT_ENVELOPE", {"for_node_id": server.node_id, "envelope": corrupted})
            kind, ack_payload, error = wire.recv_message(conn, timeout=5)
            self.assertIsNone(error)
            self.assertEqual(kind, "ARTIFACT_ENVELOPE_ACK")
            self.assertTrue(ack_payload["delivered"])  # delivery itself does not validate

            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=fi._new_id("CORR"), causation_id=fi._new_id("XFER"), timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("hash mismatch", result.error_detail)
        finally:
            server.terminate()


class TestIncompleteResultOverWire(unittest.TestCase):
    def test_completed_with_no_structured_result_is_downgraded_across_the_wire(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="broken_incomplete_capability_for_testing",
                authority_context=_authority("broken_incomplete_capability_for_testing"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_INCOMPLETE)
        finally:
            server.terminate()


class TestTimeoutOverWire(unittest.TestCase):
    def test_slow_pc_response_is_a_client_side_timeout(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport(response_timeout=0.5)
            conn = transport._raw_connection_for_testing()
            wire.send_message(conn, "TEST_HOOK", {"action": "sleep_ms", "ms": 2000})
            kind, payload, error = wire.recv_message(conn, timeout=0.5)
            self.assertIsNone(kind)
            self.assertIn("TIMEOUT", error)
        finally:
            server.terminate()


class TestProcessTerminationDuringRequest(unittest.TestCase):
    def test_pc_dying_mid_request_is_an_honest_failure_not_a_hang(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport(response_timeout=5.0)
            conn = transport._raw_connection_for_testing()
            wire.send_message(conn, "TEST_HOOK", {"action": "die"})
            kind, payload, error = wire.recv_message(conn, timeout=5.0)
            self.assertIsNone(kind)
            self.assertIsNotNone(error)
            self.assertTrue(("EOF" in error) or ("TIMEOUT" in error), error)
        finally:
            server.terminate()


class TestMismatchedCorrelationAndCausation(unittest.TestCase):
    """The wire itself carries these correctly (proven in the full round
    trip); this proves PHONE_NODE's OWN verification actually rejects a
    tampered/incorrect response rather than trusting it by construction."""

    def test_verification_rejects_wrong_correlation_id(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)

            tampered_result = fi.RemoteCapabilityResult(
                request_id=result.request_id, capability_id=result.capability_id, status=result.status,
                structured_result=result.structured_result, error_detail=result.error_detail,
                source_node_id=result.source_node_id, destination_node_id=result.destination_node_id,
                correlation_id="SOME-OTHER-CORRELATION-ID", causation_id=result.causation_id,
            )
            verification_error = verify_capability_response(cap_request, tampered_result, receipt)
            self.assertIsNotNone(verification_error)
            self.assertIn("correlation_id", verification_error)
        finally:
            server.terminate()

    def test_verification_rejects_wrong_causation_id(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)

            tampered_receipt = fi.FabricReceipt(
                receipt_id=receipt.receipt_id, correlation_id=receipt.correlation_id,
                causation_id="SOME-OTHER-CAUSATION-ID", source_node_id=receipt.source_node_id,
                destination_node_id=receipt.destination_node_id, artifact_id=receipt.artifact_id,
                sha256=receipt.sha256, capability_id=receipt.capability_id,
                transfer_state=receipt.transfer_state, capability_status=receipt.capability_status,
            )
            verification_error = verify_capability_response(cap_request, result, tampered_receipt)
            self.assertIsNotNone(verification_error)
            self.assertIn("causation_id", verification_error)
        finally:
            server.terminate()


if __name__ == "__main__":
    unittest.main()
