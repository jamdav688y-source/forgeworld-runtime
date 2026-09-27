"""Tests for FW-AUTHORITY-EXPIRY-TRANSPORT-PROOF-001 (loopback half).

Proves the authority-expiry governance rule already proven at the
primitive level (fabric/tests/test_authority_expiry.py) and at the
in-process orchestration boundary (fabric/tests/test_authority_expiry_e2e.py)
survives a REAL process-boundary transport hop: JSON serialization -> a
real multiprocessing.connection socket -> a genuinely separate OS
subprocess running fabric/loopback/pc_node_server.py -> JSON
deserialization -> the SAME unmodified process_remote_capability_request().

Fixture code (_SpawnedServer, _do_transfer) is duplicated here rather
than imported from fabric/tests/test_fabric_loopback.py, matching this
repository's own established convention: fabric/tcp/tests/test_fabric_tcp.py
already defines its own independent _SpawnedTCPServer rather than
importing fabric/tests/test_fabric_loopback.py's _SpawnedServer. No
existing test file is modified.

Zero-execution evidence: the spawned server subprocess cannot share an
in-process spy object with this test process (real process isolation),
so execution is proven the way fabric/tests/test_fabric_loopback.py's own
TestFullTwoProcessRoundTrip already proves it -- via the REAL durable
LineageStore the server subprocess writes to on its own disk.
ah_interface.handoff() (which records a lineage entry) only runs, inside
process_remote_capability_request(), after authority_permits() returns
True and before provider.invoke() -- so zero lineage records for a denied
request is real, disk-based, cross-process evidence of zero execution,
and a non-None structured_result containing the real decoded payload
(content_read's actual output) is direct evidence the real capability
ran, not just that a status code was flipped.

Stdlib unittest, a real subprocess, a real AF_UNIX/AF_PIPE loopback
socket. No external network, no phone, no cloud service.
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
from fabric.loopback.transport import LoopbackClientTransport, make_loopback_address, cleanup_loopback_address
from artifact_handoff.lineage_store import LineageStore

SERVER_SCRIPT = REPO_ROOT / "fabric" / "loopback" / "pc_node_server.py"
PHONE_ID = "PHONE-NODE-EXPIRY-LOOPBACK"

# Fixed, not wall-clock-relative on purpose -- real UTC "now" will remain
# after PAST_EXPIRY and before FUTURE_EXPIRY for the practical life of
# this suite; no clock injection exists at this transport boundary (see
# the mission's recorded exact-boundary limitation).
PAST_EXPIRY = "2020-01-01T00:00:00Z"
FUTURE_EXPIRY = "2099-01-01T00:00:00Z"
MALFORMED_EXPIRY = "not-a-timestamp"


def _authority(capability_ids, expires_at=None, actor=PHONE_ID):
    return fi.AuthorityContext(
        actor_id=actor, granted_capability_ids=tuple(capability_ids),
        granted_by="test_policy", expires_at=expires_at,
    )


class _SpawnedServer:
    """Wraps a real subprocess running pc_node_server.py, duplicated from
    fabric/tests/test_fabric_loopback.py's fixture of the same name and
    behavior (see module docstring for why it is duplicated, not
    imported)."""

    def __init__(self, node_id="PC-NODE-EXPIRY-LOOPBACK", max_messages=100, idle_timeout=6.0):
        self.node_id = node_id
        self.address, self.family = make_loopback_address(f"expiry-test-{uuid.uuid4().hex[:8]}")
        self.authkey = os.urandom(16)
        self._tmp = tempfile.TemporaryDirectory()
        self.lineage_dir = self._tmp.name
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
        self._tmp.cleanup()
        cleanup_loopback_address(self.address, self.family)


def _do_transfer(server, transport, payload=b"authority-expiry loopback probe payload",
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


class TestAuthorityWireRoundTripPreservesGovernanceFields(unittest.TestCase):
    """Section 4's critical serialization invariant, proven at the pure
    wire layer (no subprocess needed -- this isolates exactly the
    serialize/JSON/deserialize step both fabric/loopback/ and fabric/tcp/
    reuse unmodified from fabric.loopback.wire)."""

    def test_expires_at_and_governance_fields_survive_json_round_trip(self):
        original = fi.AuthorityContext(
            actor_id="ACTOR-ROUNDTRIP", granted_capability_ids=("content_read", "echo_mock"),
            granted_by="operator_default_policy", expires_at=PAST_EXPIRY,
        )
        wire_dict = json.loads(json.dumps(wire.authority_to_wire(original)))
        reconstructed, reason = wire.safe_authority_from_wire(wire_dict)
        self.assertIsNone(reason)
        self.assertEqual(reconstructed.actor_id, original.actor_id)
        self.assertEqual(reconstructed.granted_capability_ids, original.granted_capability_ids)
        self.assertEqual(reconstructed.granted_by, original.granted_by)
        self.assertEqual(reconstructed.expires_at, original.expires_at)

    def test_none_expiry_survives_round_trip_as_none(self):
        original = fi.AuthorityContext(
            actor_id="ACTOR-ROUNDTRIP", granted_capability_ids=("content_read",),
            granted_by="operator_default_policy", expires_at=None,
        )
        wire_dict = json.loads(json.dumps(wire.authority_to_wire(original)))
        reconstructed, reason = wire.safe_authority_from_wire(wire_dict)
        self.assertIsNone(reason)
        self.assertIsNone(reconstructed.expires_at)

    def test_malformed_expiry_string_survives_round_trip_unmutated(self):
        # The wire layer must not "fix" or silently normalize a malformed
        # value -- fail-closed enforcement is authority_permits()'s job at
        # evaluation time, not the transport's.
        original = fi.AuthorityContext(
            actor_id="ACTOR-ROUNDTRIP", granted_capability_ids=("content_read",),
            granted_by="operator_default_policy", expires_at=MALFORMED_EXPIRY,
        )
        wire_dict = json.loads(json.dumps(wire.authority_to_wire(original)))
        reconstructed, reason = wire.safe_authority_from_wire(wire_dict)
        self.assertIsNone(reason)
        self.assertEqual(reconstructed.expires_at, MALFORMED_EXPIRY)


class TestExpiredAuthorityOverLoopback(unittest.TestCase):
    def test_expired_authority_denied_with_zero_lineage_writes(self):
        server = _SpawnedServer()
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


class TestFutureAuthorityOverLoopback(unittest.TestCase):
    def test_future_authority_permits_and_executes_exactly_once(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            payload = b"future-authority loopback probe payload"
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


class TestNoneExpiryOverLoopback(unittest.TestCase):
    def test_non_expiring_authority_preserves_existing_execution(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            payload = b"non-expiring loopback probe payload"
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


class TestMalformedExpiryOverLoopback(unittest.TestCase):
    def test_malformed_expiry_over_wire_fails_closed_with_zero_execution(self):
        server = _SpawnedServer()
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


class TestExpiryDoesNotWeakenAllowlistOverLoopback(unittest.TestCase):
    def test_future_expiry_does_not_bypass_capability_allowlist(self):
        server = _SpawnedServer()
        try:
            transport = server.client_transport()
            env, correlation_id, transfer_result = _do_transfer(server, transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=server.node_id,
                artifact_id=env.artifact_id, capability_id="content_read",
                authority_context=_authority(("echo_mock",), expires_at=FUTURE_EXPIRY),  # wrong capability, not expired
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
