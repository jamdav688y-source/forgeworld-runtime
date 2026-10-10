"""Tests for FW-MESSAGE-IDENTITY-REPLAY-CONTRACT-001 (in-process half).

Proves fabric.interface.RequestReplayGuard establishes an at-most-once
execution gate for process_remote_capability_request(), keyed by
RemoteCapabilityRequest.request_id -- the smallest existing stable
identifier discovered for a logical capability request (generated once,
by the sender, before any transfer/transport step, and passed through
every layer verbatim).

Discovery finding this file exists to fix: without replay_guard, TWO
capability requests carrying the SAME request_id (a literal message
replay, as opposed to two genuinely distinct requests that happen to
target the same artifact -- see fabric/tests/test_fabric_contract.py::
TestDuplicateArtifact::test_identical_resubmission_is_not_a_conflict,
which proves the LATTER already executes twice today, correctly) would
invoke the registered capability provider twice, because nothing in
process_remote_capability_request() keyed dispatch on request_id before
this mission. FabricArtifactIndex only rejects CONFLICTING content under
the same artifact_id; it does not recognize replay of an identical
request. LineageStore deduplicates the artifact MANIFEST write, not
capability invocation.

Stdlib unittest, InMemoryFabricTransport only (no subprocess, no real
transport hop -- that half is covered by
test_message_identity_replay_loopback.py / _tcp.py). Zero-execution
evidence uses a spy capability provider (invocation_count), the same
technique fabric/tests/test_authority_expiry_e2e.py already established.
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.loopback import wire
from fabric.transports import InMemoryFabricTransport

PC_ID = "PC-NODE-REPLAY"
PHONE_ID = "PHONE-NODE-REPLAY"

PAST_EXPIRY = "2020-01-01T00:00:00Z"
FUTURE_EXPIRY = "2099-01-01T00:00:00Z"


class _SpyCapabilityProvider:
    def __init__(self, capability_id):
        self.capability_id = capability_id
        self.invocation_count = 0

    def invoke(self, manifest_dict, payload):
        self.invocation_count += 1
        return (fi.CAP_COMPLETED, {"echo_len": len(payload)}, None)


def _authority(capability_ids, expires_at=None, actor=PHONE_ID):
    return fi.AuthorityContext(
        actor_id=actor, granted_capability_ids=tuple(capability_ids),
        granted_by="test_policy", expires_at=expires_at,
    )


def _transfer_and_build_request(transport, spy, cap_authority, request_id=None,
                                 payload=b"replay-contract probe payload", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    xfer_request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=PC_ID, authority_context=_authority((spy.capability_id,)),
        correlation_id=correlation_id,
    )
    xfer_result = fi.submit_transfer(xfer_request, transport)
    assert xfer_result.transfer_state == fi.TRANSFER_COMPLETED
    cap_request = fi.RemoteCapabilityRequest(
        request_id=request_id or fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
        artifact_id=env.artifact_id, capability_id=spy.capability_id, authority_context=cap_authority,
        correlation_id=correlation_id, causation_id=xfer_result.transfer_id, timeout_seconds=5,
    )
    return env, cap_request


class _ReplayTestCase(unittest.TestCase):
    def setUp(self):
        self.spy = _SpyCapabilityProvider("replay_spy_" + fi.uuid.uuid4().hex[:8])
        fi.register_capability(self.spy)
        self._tmp = tempfile.TemporaryDirectory()
        self.guard = fi.RequestReplayGuard(Path(self._tmp.name))

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)
        self._tmp.cleanup()


class TestFirstDeliveryExecutesExactlyOnce(_ReplayTestCase):
    """TEST 1."""

    def test_first_delivery_executes(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,)))
        result, receipt = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestImmediateDuplicateDoesNotExecuteAgain(_ReplayTestCase):
    """TEST 2."""

    def test_same_request_object_replayed_in_process(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,)))
        first, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        second, receipt2 = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(second.structured_result, first.structured_result)
        self.assertEqual(self.spy.invocation_count, 1)  # NOT 2


class TestSerializedDuplicateDoesNotExecuteAgain(_ReplayTestCase):
    """TEST 3 -- proves dedup is keyed by request_id VALUE, not Python
    object identity: the replayed request is a freshly reconstructed
    object from a real JSON round trip, not the original in-memory one."""

    def test_wire_roundtripped_duplicate_does_not_execute_again(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,)))
        first, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        wire_dict = wire.capability_request_to_wire(req)
        reconstructed_req, reason = wire.safe_capability_request_from_wire(wire_dict)
        self.assertIsNone(reason)
        self.assertIsNot(reconstructed_req, req)  # genuinely a different object
        self.assertEqual(reconstructed_req.request_id, req.request_id)

        second, _ = fi.process_remote_capability_request(reconstructed_req, transport, replay_guard=self.guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestRetryAfterLostResponseGetsOriginalDisposition(_ReplayTestCase):
    """TEST 6 / crash-window C (completion persisted, response lost,
    sender retries): the retry must get back the TRUE original outcome,
    not a fresh execution and not a misleading failure."""

    def test_retry_returns_original_completed_result_not_a_fresh_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        payload = b"response-loss retry probe payload"
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,)), payload=payload)
        first, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(first.structured_result["echo_len"], len(payload))

        # Sender "never saw" `first` (simulated response loss) and retries
        # with the identical request object.
        retry, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(retry.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(retry.structured_result["echo_len"], len(payload))
        self.assertEqual(self.spy.invocation_count, 1)


class TestDistinctRequestIdExecutesIndependently(_ReplayTestCase):
    """TEST 7 -- proves dedup is based on logical request identity, not
    payload/capability coincidence: same capability, same authority
    shape, genuinely different request_id (and therefore a genuinely
    distinct artifact transfer, since each logical request needs its own
    delivered envelope) -- both must execute."""

    def test_two_distinct_request_ids_both_execute(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        shared_authority = _authority((self.spy.capability_id,))

        env1, req1 = _transfer_and_build_request(transport, self.spy, shared_authority)
        result1, _ = fi.process_remote_capability_request(req1, transport, replay_guard=self.guard)
        self.assertEqual(result1.status, fi.CAP_COMPLETED)

        env2, req2 = _transfer_and_build_request(transport, self.spy, shared_authority)
        self.assertNotEqual(req1.request_id, req2.request_id)
        result2, _ = fi.process_remote_capability_request(req2, transport, replay_guard=self.guard)
        self.assertEqual(result2.status, fi.CAP_COMPLETED)

        self.assertEqual(self.spy.invocation_count, 2)


class TestExpiredDuplicateNeverExecutes(_ReplayTestCase):
    """TEST 8 -- a request completed while its authority was valid, then
    replayed under a SECOND RemoteCapabilityRequest object sharing the
    same request_id but carrying an EXPIRED authority_context (modeling
    time having passed before the replay arrived): must return the
    ORIGINAL completed disposition without re-evaluating authority at
    all, and must never invoke the capability again. Proves replay
    resolution happens before, and is independent of, a fresh authority
    check -- a duplicate can neither gain nor lose authority."""

    def test_replay_with_now_expired_authority_still_returns_original_completion(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,), expires_at=FUTURE_EXPIRY))
        first, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        expired_replay = fi.RemoteCapabilityRequest(
            request_id=req.request_id, source_node_id=req.source_node_id, destination_node_id=req.destination_node_id,
            artifact_id=req.artifact_id, capability_id=req.capability_id,
            authority_context=_authority((self.spy.capability_id,), expires_at=PAST_EXPIRY),
            correlation_id=req.correlation_id, causation_id=req.causation_id, timeout_seconds=req.timeout_seconds,
        )
        second, _ = fi.process_remote_capability_request(expired_replay, transport, replay_guard=self.guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)  # never executed under the expired replay


class TestReplayNeverWeakensADenial(_ReplayTestCase):
    """A request denied on first delivery (e.g. unauthorized) must stay
    denied on replay -- a duplicate must not get a second, more
    favorable authority evaluation."""

    def test_denied_first_delivery_stays_denied_on_replay_even_with_valid_authority(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority(()))  # empty grant: denied
        first, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)

        # Replay carries a NOW-VALID authority for the same request_id --
        # must still be recognized as the same (denied) logical request,
        # not silently re-authorized.
        favorable_replay = fi.RemoteCapabilityRequest(
            request_id=req.request_id, source_node_id=req.source_node_id, destination_node_id=req.destination_node_id,
            artifact_id=req.artifact_id, capability_id=req.capability_id,
            authority_context=_authority((self.spy.capability_id,), expires_at=FUTURE_EXPIRY),
            correlation_id=req.correlation_id, causation_id=req.causation_id, timeout_seconds=req.timeout_seconds,
        )
        second, _ = fi.process_remote_capability_request(favorable_replay, transport, replay_guard=self.guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_DENIED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestDurableAcrossGuardReinstantiation(_ReplayTestCase):
    """TEST 9 (in-process proxy for process restart): a real process
    restart re-instantiates RequestReplayGuard from the same on-disk
    directory (exactly what pc_node_server.py's run_server() does on
    every launch) -- re-creating the Python object from the same root
    must see the durable record a DIFFERENT, now-discarded guard object
    already wrote."""

    def test_fresh_guard_instance_over_the_same_directory_still_recognizes_the_duplicate(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,)))
        first, _ = fi.process_remote_capability_request(req, transport, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        restarted_guard = fi.RequestReplayGuard(Path(self._tmp.name))  # simulates process restart
        self.assertIsNot(restarted_guard, self.guard)
        second, _ = fi.process_remote_capability_request(req, transport, replay_guard=restarted_guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestReplayGuardOmittedPreservesPriorBehavior(_ReplayTestCase):
    """Backward compatibility: replay_guard is optional and defaults to
    None. Without it, behavior is byte-identical to every prior mission's
    proof -- including the pre-existing, still-correct double execution
    of two genuinely DISTINCT requests sharing an artifact_id (see this
    file's module docstring)."""

    def test_omitting_replay_guard_allows_the_same_request_id_to_execute_twice(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, req = _transfer_and_build_request(transport, self.spy, _authority((self.spy.capability_id,)))
        first, _ = fi.process_remote_capability_request(req, transport)  # no replay_guard
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)
        # A second call with the SAME request_id fails honestly (no
        # envelope left to pull -- pull() is destructive), demonstrating
        # this is NOT principled replay protection, just an accidental
        # side effect, exactly as this mission's discovery phase found.
        second, _ = fi.process_remote_capability_request(req, transport)
        self.assertEqual(second.status, fi.CAP_FAILED)
        self.assertIn("no envelope", second.error_detail)
        self.assertEqual(self.spy.invocation_count, 1)


if __name__ == "__main__":
    unittest.main()
