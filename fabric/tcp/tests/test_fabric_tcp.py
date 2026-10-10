"""Tests for FW-FABRIC-DEVICE-BOUNDARY-001 (PC-side, local proof only).

Stdlib `unittest`. Spawns fabric/tcp/pc_node_server.py as a genuinely
separate OS process, bound to 127.0.0.1 (loopback interface) on an
OS-assigned ephemeral port -- this proves the real TCP/AF_INET code path
(a real socket, a real three-way handshake, the same multiprocessing.
connection authkey challenge a LAN deployment would use) without ever
exposing a listener beyond this machine. Nothing here reaches, requires,
or simulates the physical phone -- that is deliberately a separate,
unverified claim (see the mission's PHYSICAL_TRANSPORT_REACHABLE /
PHONE_TO_PC_GOVERNED_ROUND_TRIP_DEMONSTRATED distinction).

The phone-side role in every test is played by
fabric.loopback.transport.LoopbackClientTransport, UNMODIFIED --
proving directly that the exact same adapter class already validated
over AF_UNIX also works, unchanged, over AF_INET. TCP is an adapter, not
the architecture.
"""
import base64
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.loopback import wire
from fabric.loopback.transport import LoopbackClientTransport, verify_capability_response
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "tcp" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-TCP-TEST"
DEFAULT_MAX_MESSAGE_BYTES = 65536


def _authority(*capability_ids):
    return fi.AuthorityContext(actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids), granted_by="test_policy")


class _SpawnedTCPServer:
    def __init__(self, node_id="PC-NODE-MAIN", max_messages=20, idle_timeout=6.0,
                 max_runtime_seconds=30.0, max_message_bytes=DEFAULT_MAX_MESSAGE_BYTES):
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


def _do_transfer(server, transport, payload=b"synthetic harvested observation over real TCP",
                  declared_content_type="text/plain", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type=declared_content_type, artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=server.node_id, authority_context=_authority("content_read"), correlation_id=correlation_id,
    )
    result = fi.submit_transfer(request, transport)
    return env, correlation_id, result


class TestFullTCPRoundTrip(unittest.TestCase):
    def test_phone_to_pc_to_phone_over_real_tcp_socket(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            payload = b"Observed note: prospective contact mentioned a hiring need."
            env, correlation_id, transfer_result = _do_transfer(server, transport, payload=payload)

            self.assertEqual(transfer_result.transfer_state, fi.TRANSFER_COMPLETED)
            self.assertTrue(transfer_result.integrity_verified)

            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            self.assertIsNone(transport.send_capability_request(cap_request))
            result, receipt, error = transport.recv_capability_response(timeout=10)
            self.assertIsNone(error, error)
            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())

            self.assertIsNone(verify_capability_response(cap_request, result, receipt))

            lineage_store = LineageStore(Path(server.lineage_dir))
            records = lineage_store.list_all()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["sha256"], env.sha256)

            transport.send_shutdown()
            transport.close()
            server.proc.wait(timeout=5)
            self.assertEqual(server.proc.returncode, 0)
        finally:
            server.terminate()


class TestCapabilityAllowlistEnforced(unittest.TestCase):
    def test_echo_mock_is_not_registered_on_this_listener(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="echo_mock", authority_context=_authority("echo_mock"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            transport.send_capability_request(cap_request)
            result, receipt, error = transport.recv_capability_response(timeout=5)
            self.assertIsNone(error)
            self.assertEqual(result.status, fi.CAP_UNSUPPORTED)
            self.assertIn("allowlist", result.error_detail)
        finally:
            server.terminate()


class TestOneShotListenerRefusesSecondConnection(unittest.TestCase):
    def test_second_connection_attempt_after_first_is_refused(self):
        server = _SpawnedTCPServer()
        try:
            first = server.client_transport()
            first._ensure_connected()
            self.assertIsNotNone(first._conn)

            second = server.client_transport(connect_timeout=2.0)
            reason = second._ensure_connected()
            self.assertIsNotNone(reason, "a second connection to a one-shot listener must be refused, not accepted")
        finally:
            server.terminate()


class TestMessageTooLarge(unittest.TestCase):
    def test_oversized_message_is_rejected(self):
        server = _SpawnedTCPServer(max_message_bytes=1024)
        try:
            transport = server.client_transport()
            conn = transport._raw_connection_for_testing()
            oversized_payload = {"junk": "x" * 100_000}
            wire.send_message(conn, "ARTIFACT_ENVELOPE", {"for_node_id": server.node_id, "envelope": oversized_payload})
            # The server's recv_message(max_bytes=1024) rejects this and
            # exits its loop honestly rather than crash or hang.
            server.proc.wait(timeout=10)
            stderr = server.proc.stderr.read() if server.proc.stderr else ""
            self.assertEqual(server.proc.returncode, 0, stderr)
        finally:
            server.terminate()


class TestHashMismatchOverTCP(unittest.TestCase):
    def test_in_transit_corruption_caught_by_pc_independent_reverification(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            env = fi.build_artifact_envelope(PHONE_ID, b"authentic tcp payload data", declared_content_type="text/plain")
            conn = transport._raw_connection_for_testing()

            wire_env = wire.envelope_to_wire(env)
            corrupted = dict(wire_env)
            flipped = bytes(b ^ 0xFF for b in env.payload)
            corrupted["payload_b64"] = base64.b64encode(flipped).decode()
            wire.send_message(conn, "ARTIFACT_ENVELOPE", {"for_node_id": server.node_id, "envelope": corrupted})
            kind, ack_payload, error = wire.recv_message(conn, timeout=5)
            self.assertIsNone(error)
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


class TestUnauthorizedOverTCP(unittest.TestCase):
    def test_capability_not_in_granted_scope_is_unauthorized(self):
        server = _SpawnedTCPServer()
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


class TestUnknownNodeOverTCP(unittest.TestCase):
    def test_wrong_destination_node_id_is_rejected(self):
        server = _SpawnedTCPServer()
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


class TestDuplicateArtifactOverTCP(unittest.TestCase):
    def test_same_artifact_id_different_content_is_a_conflict(self):
        server = _SpawnedTCPServer()
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


class TestMalformedMessageOverTCP(unittest.TestCase):
    def test_malformed_json_over_real_socket_is_honest_not_a_crash(self):
        server = _SpawnedTCPServer()
        try:
            transport = server.client_transport()
            conn = transport._raw_connection_for_testing()
            conn.send_bytes(b"not json at all {{{")
            server.proc.wait(timeout=10)
            self.assertEqual(server.proc.returncode, 0)
        finally:
            server.terminate()


class TestTermuxClientScriptLocalProof(unittest.TestCase):
    """Runs the EXACT fabric/tcp/termux_phone_client.py file the operator
    will copy to the physical phone, as its own real subprocess (not
    imported -- proving the actual artifact, not a stand-in), against a
    locally spawned pc_node_server.py over a real TCP socket. This is
    the strongest local proxy for the physical round trip available in
    this sandbox; it does not and cannot substitute for output from the
    real phone (see the mission's evidence-class distinction)."""

    def test_termux_client_subprocess_completes_a_verified_round_trip(self):
        server = _SpawnedTCPServer()
        client_script = REPO_ROOT / "fabric" / "tcp" / "termux_phone_client.py"
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(client_script),
                    "--host", server.host, "--port", str(server.port),
                    "--authkey", server.authkey.hex(), "--pc-node-id", server.node_id,
                    "--text", "local subprocess proof of the exact termux client artifact",
                ],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("PHONE_TO_PC_GOVERNED_ROUND_TRIP_VERIFIED", proc.stdout)
        finally:
            server.terminate()

    def test_termux_client_reports_wrong_authkey_honestly(self):
        server = _SpawnedTCPServer()
        client_script = REPO_ROOT / "fabric" / "tcp" / "termux_phone_client.py"
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(client_script),
                    "--host", server.host, "--port", str(server.port),
                    "--authkey", os.urandom(16).hex(),  # deliberately wrong
                    "--pc-node-id", server.node_id, "--connect-timeout", "3",
                ],
                capture_output=True, text=True, timeout=15,
            )
            self.assertNotEqual(proc.returncode, 0)
        finally:
            server.terminate()


class TestDestinationAbsentOverTCP(unittest.TestCase):
    def test_no_listener_on_port_is_reported_unreachable(self):
        # Bind nothing; pick a port unlikely to be in use and connect to it.
        transport = LoopbackClientTransport(("127.0.0.1", 18765 + (os.getpid() % 500)), "AF_INET", os.urandom(16), connect_timeout=1.0)
        env = fi.build_artifact_envelope(PHONE_ID, b"x", declared_content_type="text/plain")
        request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id="PC-NODE-MAIN", authority_context=_authority("content_read"),
            correlation_id=fi._new_id("CORR"),
        )
        result = fi.submit_transfer(request, transport)
        self.assertEqual(result.transfer_state, fi.TRANSFER_UNREACHABLE)
        self.assertIn("not reachable", result.error_detail)


if __name__ == "__main__":
    unittest.main()
