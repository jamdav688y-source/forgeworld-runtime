"""Tests for FW-TWO-NODE-FABRIC-CONTRACT-001.

Stdlib `unittest` (same precedent as every other test file in this
program). Every fixture is synthetic and local. No network, no phone
connection, no Ollama, no model, no external API, no cloud service, no
LinkedIn access, no OpenClaw, no Hermes, no SSH, no new service is
created or required anywhere in this file -- the only transport is
fabric.transports.InMemoryFabricTransport, and the only capabilities
invoked are content_readers (real, already tested) and a deliberate mock.
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.transports import InMemoryFabricTransport
from fabric import capabilities as fabric_capabilities  # noqa: F401 -- registers content_read/echo_mock
from artifact_handoff.lineage_store import LineageStore

PC_ID = "PC-NODE-MAIN"
PHONE_ID = "PHONE-NODE-FIELD"

PC_IDENTITY = fi.NodeIdentity(node_id=PC_ID, node_type=fi.NODE_TYPE_PC, display_name="Primary PC")
PHONE_IDENTITY = fi.NodeIdentity(node_id=PHONE_ID, node_type=fi.NODE_TYPE_PHONE, display_name="Field Phone")


def _authority(*capability_ids, actor=PHONE_ID):
    return fi.AuthorityContext(actor_id=actor, granted_capability_ids=tuple(capability_ids), granted_by="operator_default_policy")


def _transfer(transport, payload=b"synthetic harvested observation text", declared_content_type="text/plain", artifact_id=None):
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type=declared_content_type, artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=PC_ID, authority_context=_authority("content_read"), correlation_id=correlation_id,
    )
    result = fi.submit_transfer(request, transport)
    return env, correlation_id, result


class TestNodeIdentityAndAdvertisement(unittest.TestCase):
    def test_node_identity_types_are_constrained(self):
        self.assertEqual(PC_IDENTITY.node_type, fi.NODE_TYPE_PC)
        self.assertEqual(PHONE_IDENTITY.node_type, fi.NODE_TYPE_PHONE)
        with self.assertRaises(fi.FabricError):
            fi.NodeIdentity(node_id="X", node_type="CLOUD_NODE", display_name="bad")

    def test_capability_advertisement_matches_registered_capabilities(self):
        ads = [
            fi.NodeCapabilityAdvertisement(node_id=PC_ID, capability_id=cap_id, tags=())
            for cap_id in fi.CAPABILITIES
        ]
        advertised_ids = {a.capability_id for a in ads}
        self.assertEqual(advertised_ids, {"content_read", "echo_mock"})


class TestFullRoundTrip(unittest.TestCase):
    """PHONE_NODE -> FABRIC -> PC_NODE -> FABRIC -> PHONE_NODE, proven in
    one process with an in-memory transport."""

    def test_phone_creates_transfers_pc_processes_phone_verifies(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        with tempfile.TemporaryDirectory() as d:
            lineage_store = LineageStore(Path(d) / "lineage")
            artifact_index = fi.FabricArtifactIndex()

            # PHONE_NODE: create synthetic harvested artifact, wrap in envelope, hash, submit.
            payload = b"Observed note: prospective contact mentioned a hiring need."
            env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain")
            correlation_id = fi._new_id("CORR")
            authority = _authority("content_read")

            transfer_request = fi.TransferRequest(
                request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
                destination_node_id=PC_ID, authority_context=authority, correlation_id=correlation_id,
            )

            # FABRIC: validate, verify integrity, transfer via in-memory transport.
            transfer_result = fi.submit_transfer(transfer_request, transport)
            self.assertEqual(transfer_result.transfer_state, fi.TRANSFER_COMPLETED)
            self.assertTrue(transfer_result.integrity_verified)
            self.assertEqual(transfer_result.trust_status, fi.TRUST_STATUS)
            self.assertEqual(transfer_result.possession_status, fi.POSSESSION_STATUS)

            # PC_NODE: receive, verify hash again, preserve provenance, route, produce result + receipt.
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=authority,
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            result, receipt = fi.process_remote_capability_request(
                cap_request, transport, lineage_store=lineage_store, artifact_index=artifact_index,
            )

            self.assertEqual(result.status, fi.CAP_COMPLETED)
            self.assertEqual(result.structured_result["text_content"], payload.decode())
            self.assertEqual(result.causation_id, cap_request.request_id)
            self.assertEqual(cap_request.causation_id, transfer_result.transfer_id)

            # FABRIC returns result to PHONE_NODE (same objects; no second hop needed
            # in-process, but the receipt is what a real transport would carry back).
            self.assertEqual(receipt.transfer_state, fi.TRANSFER_COMPLETED)
            self.assertEqual(receipt.capability_status, fi.CAP_COMPLETED)
            self.assertEqual(receipt.sha256, env.sha256)

            # PHONE_NODE verifies the result: recomputes the receipt id deterministically.
            recomputed = fi.compute_receipt_id(
                receipt.correlation_id, receipt.causation_id, receipt.source_node_id, receipt.destination_node_id,
                receipt.artifact_id, receipt.sha256, receipt.capability_id, receipt.transfer_state, receipt.capability_status,
            )
            self.assertEqual(receipt.receipt_id, recomputed)

            # PC_NODE genuinely preserved provenance via the real artifact_handoff + lineage_store.
            records = lineage_store.list_all()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["sha256"], env.sha256)
            self.assertEqual(records[0]["detected_content_type"], "text/plain")


class TestUnreachableNode(unittest.TestCase):
    def test_transfer_to_unregistered_node_is_unreachable(self):
        transport = InMemoryFabricTransport(registered_nodes=())  # PC never registered
        _, _, result = _transfer(transport)
        self.assertEqual(result.transfer_state, fi.TRANSFER_UNREACHABLE)
        self.assertIn("not reachable", result.error_detail)


class TestMalformedEnvelope(unittest.TestCase):
    def test_size_mismatch_is_rejected(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env = fi.build_artifact_envelope(PHONE_ID, b"real payload", declared_content_type="text/plain")
        bad_env = fi.ArtifactEnvelope(
            envelope_id=env.envelope_id, artifact_id=env.artifact_id, source_node_id=env.source_node_id,
            payload=env.payload, sha256=env.sha256, size=999999, declared_content_type=env.declared_content_type,
        )
        request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=bad_env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority("content_read"), correlation_id=fi._new_id("CORR"),
        )
        result = fi.submit_transfer(request, transport)
        self.assertEqual(result.transfer_state, fi.TRANSFER_REJECTED)
        self.assertIn("does not match actual payload length", result.error_detail)


class TestHashMismatch(unittest.TestCase):
    def test_tampered_payload_is_rejected(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env = fi.build_artifact_envelope(PHONE_ID, b"original payload", declared_content_type="text/plain")
        tampered = fi.ArtifactEnvelope(
            envelope_id=env.envelope_id, artifact_id=env.artifact_id, source_node_id=env.source_node_id,
            payload=b"a tampered payload of the same declared size!!", sha256=env.sha256,
            size=len(b"a tampered payload of the same declared size!!"), declared_content_type=env.declared_content_type,
        )
        request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=tampered, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority("content_read"), correlation_id=fi._new_id("CORR"),
        )
        result = fi.submit_transfer(request, transport)
        self.assertEqual(result.transfer_state, fi.TRANSFER_REJECTED)
        self.assertIn("hash mismatch", result.error_detail)


class TestUnsupportedCapability(unittest.TestCase):
    def test_unregistered_capability_id_is_unsupported(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, correlation_id, transfer_result = _transfer(transport)
        cap_request = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id="translate_klingon", authority_context=_authority("translate_klingon"),
            correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
        )
        result, receipt = fi.process_remote_capability_request(cap_request, transport)
        self.assertEqual(result.status, fi.CAP_UNSUPPORTED)
        self.assertEqual(receipt.capability_status, fi.CAP_UNSUPPORTED)


class TestUnauthorizedRequest(unittest.TestCase):
    def test_capability_not_in_granted_scope_is_unauthorized(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, correlation_id, transfer_result = _transfer(transport)
        narrow_authority = _authority()  # empty grant: the phone gets NOTHING by default
        cap_request = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id="content_read", authority_context=narrow_authority,
            correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
        )
        result, receipt = fi.process_remote_capability_request(cap_request, transport)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertIn("not authorized", result.error_detail)

    def test_phone_never_has_unrestricted_authority_by_default(self):
        # Demonstrates the architectural rule directly: constructing an
        # AuthorityContext requires an explicit allowlist; there is no
        # wildcard/"*" value anywhere in authority_permits().
        broad_but_explicit = _authority("content_read", "echo_mock")
        self.assertFalse(fi.authority_permits(broad_but_explicit, "arbitrary_shell_execution"))
        self.assertFalse(fi.authority_permits(broad_but_explicit, "anything_not_explicitly_listed"))


class TestDuplicateArtifact(unittest.TestCase):
    def test_same_artifact_id_different_content_is_a_conflict(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        artifact_index = fi.FabricArtifactIndex()
        shared_id = fi.ah_interface.new_artifact_id()

        env1, corr1, xfer1 = _transfer(transport, payload=b"first version of the content", artifact_id=shared_id)
        req1 = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env1.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
            correlation_id=corr1, causation_id=xfer1.transfer_id, timeout_seconds=5,
        )
        result1, _ = fi.process_remote_capability_request(req1, transport, artifact_index=artifact_index)
        self.assertEqual(result1.status, fi.CAP_COMPLETED)

        env2, corr2, xfer2 = _transfer(transport, payload=b"a DIFFERENT content reusing the same artifact_id", artifact_id=shared_id)
        req2 = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env2.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
            correlation_id=corr2, causation_id=xfer2.transfer_id, timeout_seconds=5,
        )
        result2, receipt2 = fi.process_remote_capability_request(req2, transport, artifact_index=artifact_index)
        self.assertEqual(result2.status, fi.CAP_DUPLICATE_CONFLICT)
        self.assertEqual(receipt2.capability_status, fi.CAP_DUPLICATE_CONFLICT)

    def test_identical_resubmission_is_not_a_conflict(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        artifact_index = fi.FabricArtifactIndex()
        shared_id = fi.ah_interface.new_artifact_id()
        payload = b"same content resubmitted"

        for _ in range(2):
            env, corr, xfer = _transfer(transport, payload=payload, artifact_id=shared_id)
            req = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
                artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=corr, causation_id=xfer.transfer_id, timeout_seconds=5,
            )
            result, _ = fi.process_remote_capability_request(req, transport, artifact_index=artifact_index)
            self.assertEqual(result.status, fi.CAP_COMPLETED)


class TestIncompleteResult(unittest.TestCase):
    def test_capability_claiming_completed_with_no_result_is_downgraded_honestly(self):
        class _BrokenCapability:
            capability_id = "broken_completes_with_nothing"

            def invoke(self, manifest_dict, payload):
                return fi.CAP_COMPLETED, None, None  # claims success but provides nothing

        fi.register_capability(_BrokenCapability())
        try:
            transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
            env, correlation_id, transfer_result = _transfer(transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
                artifact_id=env.artifact_id, capability_id="broken_completes_with_nothing",
                authority_context=_authority("broken_completes_with_nothing"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            result, receipt = fi.process_remote_capability_request(cap_request, transport)
            self.assertEqual(result.status, fi.CAP_INCOMPLETE)
            self.assertIn("returned no structured_result", result.error_detail)
        finally:
            del fi.CAPABILITIES["broken_completes_with_nothing"]

    def test_capability_raising_is_caught_as_failed_not_propagated(self):
        class _ExplodingCapability:
            capability_id = "explodes"

            def invoke(self, manifest_dict, payload):
                raise RuntimeError("boom")

        fi.register_capability(_ExplodingCapability())
        try:
            transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
            env, correlation_id, transfer_result = _transfer(transport)
            cap_request = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
                artifact_id=env.artifact_id, capability_id="explodes", authority_context=_authority("explodes"),
                correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
            )
            result, receipt = fi.process_remote_capability_request(cap_request, transport)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("unexpected exception", result.error_detail)
        finally:
            del fi.CAPABILITIES["explodes"]


class TestTransportFailure(unittest.TestCase):
    def test_simulated_transport_failure_is_reported_honestly(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,), failing_nodes=(PC_ID,))
        _, _, result = _transfer(transport)
        self.assertEqual(result.transfer_state, fi.TRANSFER_FAILED)
        self.assertIn("simulated transport failure", result.error_detail)

    def test_transport_raising_is_caught_as_failed_not_propagated(self):
        class _ExplodingTransport:
            transport_id = "exploding"

            def deliver(self, destination_node_id, env):
                raise ConnectionError("cable unplugged")

            def pull(self, node_id):
                return []

        env = fi.build_artifact_envelope(PHONE_ID, b"payload", declared_content_type="text/plain")
        request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority("content_read"), correlation_id=fi._new_id("CORR"),
        )
        result = fi.submit_transfer(request, _ExplodingTransport())
        self.assertEqual(result.transfer_state, fi.TRANSFER_FAILED)
        self.assertIn("unexpected exception", result.error_detail)


class TestSemanticInvariants(unittest.TestCase):
    """transfer != trust; receipt != truth; model output != evidence;
    successful execution != promotion; node possession != execution
    authority -- proven as fixed, non-overridable properties."""

    def test_all_fixed_invariants_on_a_successful_round_trip(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, correlation_id, transfer_result = _transfer(transport)
        cap_request = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
            correlation_id=correlation_id, causation_id=transfer_result.transfer_id, timeout_seconds=5,
        )
        result, receipt = fi.process_remote_capability_request(cap_request, transport)

        self.assertEqual(transfer_result.trust_status, "TRANSFERRED_NOT_TRUSTED")
        self.assertEqual(transfer_result.possession_status, fi.POSSESSION_STATUS)
        self.assertEqual(result.evidence_status, "NOT_EVIDENCE")
        self.assertEqual(result.promotion_status, "NOT_PROMOTED")
        self.assertEqual(result.possession_status, fi.POSSESSION_STATUS)
        self.assertEqual(receipt.truth_status, "RECEIPT_NOT_TRUTH")
        self.assertEqual(receipt.evidence_status, "NOT_EVIDENCE")
        self.assertEqual(receipt.promotion_status, "NOT_PROMOTED")
        self.assertEqual(receipt.possession_status, fi.POSSESSION_STATUS)

    def test_invariant_properties_cannot_be_overridden_via_constructor(self):
        with self.assertRaises(TypeError):
            fi.RemoteCapabilityResult(
                request_id="X", capability_id="content_read", status=fi.CAP_COMPLETED,
                structured_result={"ok": True}, error_detail=None, source_node_id=PC_ID,
                destination_node_id=PHONE_ID, correlation_id="C", causation_id="X",
                evidence_status="EVIDENCE",  # not a real constructor field
            )


class TestDeterministicReceiptGeneration(unittest.TestCase):
    def test_same_facts_produce_the_same_receipt_id(self):
        args = ("CORR-1", "CAUSE-1", PHONE_ID, PC_ID, "ART-x", "0" * 64, "content_read", fi.TRANSFER_COMPLETED, fi.CAP_COMPLETED)
        self.assertEqual(fi.compute_receipt_id(*args), fi.compute_receipt_id(*args))

    def test_two_separate_processing_calls_of_the_same_facts_agree(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        payload = b"stable content for determinism check"
        artifact_id = fi.ah_interface.new_artifact_id()

        receipts = []
        for _ in range(2):
            transport2 = InMemoryFabricTransport(registered_nodes=(PC_ID,))
            env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id)
            correlation_id, causation_id = "CORR-FIXED", "CAUSE-FIXED"
            request = fi.TransferRequest(
                request_id="XFERREQ-FIXED", envelope=env, source_node_id=PHONE_ID, destination_node_id=PC_ID,
                authority_context=_authority("content_read"), correlation_id=correlation_id,
            )
            transport2.deliver(PC_ID, env)
            cap_request = fi.RemoteCapabilityRequest(
                request_id="CAPREQ-FIXED", source_node_id=PHONE_ID, destination_node_id=PC_ID,
                artifact_id=artifact_id, capability_id="content_read", authority_context=_authority("content_read"),
                correlation_id=correlation_id, causation_id=causation_id, timeout_seconds=5,
            )
            _, receipt = fi.process_remote_capability_request(cap_request, transport2)
            receipts.append(receipt.receipt_id)

        self.assertEqual(receipts[0], receipts[1])


if __name__ == "__main__":
    unittest.main()
