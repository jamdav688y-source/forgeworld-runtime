"""Tests for MISSION: FW-FABRIC-INTEGRATION-PROBE-001.

The governed fabric path (process_remote_capability_request ->
artifact_handoff.handoff -> route_to_capability) must never perform live
capability discovery implicitly. Reachability is either supplied
explicitly by the caller, or routing is recorded as
REACHABILITY_NOT_SUPPLIED; discover.probe_all() runs only when a caller
explicitly passes allow_live_discovery=True. Routing stays separate from
execution authorization, and a reachability record is never evidence of
execution.

Every test here also re-proves the full governed chain (pairing, key,
integrity, peer identity, replay, authority, receipt) still behaves as
before with reachability wired through.

Stdlib unittest, InMemoryFabricTransport only. discover.probe_all is
patched to raise in every test that must not probe, so an implicit probe
fails the test rather than being silently swallowed.
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artifact_handoff import interface as ah  # noqa: E402
from artifact_handoff.lineage_store import LineageStore  # noqa: E402
from capabilities import discover  # noqa: E402
from fabric import interface as fi  # noqa: E402
from fabric.transports import InMemoryFabricTransport  # noqa: E402

PC_ID = "PC-NODE-REACH"
PHONE_ID = "PHONE-NODE-REACH"

# text/plain routes on tags ["research", "documentation"]; claude_code
# carries both in capabilities/registry.json.
ROUTABLE_CAPABILITY = "claude_code"
INJECTED_REACHABILITY = {
    ROUTABLE_CAPABILITY: {"reachability_confidence": 1.0, "evidence": "injected deterministic fixture"},
}


def _probe_forbidden(*args, **kwargs):
    raise AssertionError("discover.probe_all() was called: live discovery is not authorized here")


class _HarmlessCapability:
    """Harmless in-memory capability: counts invocations, reports payload length."""

    def __init__(self):
        self.capability_id = "reach_harmless_" + fi.uuid.uuid4().hex[:8]
        self.invocation_count = 0

    def invoke(self, manifest_dict, payload):
        self.invocation_count += 1
        return (fi.CAP_COMPLETED, {"payload_len": len(payload)}, None)


def _authority(capability_ids, expires_at=None):
    return fi.AuthorityContext(
        actor_id=PHONE_ID, granted_capability_ids=tuple(capability_ids),
        granted_by="test_policy", expires_at=expires_at,
    )


def _utc_stamp(delta):
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


class _GovernedChainTestCase(unittest.TestCase):
    def setUp(self):
        self.capability = _HarmlessCapability()
        fi.register_capability(self.capability)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.key_store = fi.LocalKeyStore(root / "keys")
        self.pairing_store = fi.PairingStore(root / "pairing")
        self.peer_store = fi.PeerIdentityStore(root / "peers")
        self.replay_root = root / "replay"
        self.replay_guard = fi.RequestReplayGuard(self.replay_root)
        self.lineage_root = root / "lineage"
        self.lineage_store = LineageStore(self.lineage_root)
        self.probe_patch = mock.patch.object(discover, "probe_all", side_effect=_probe_forbidden)
        self.probe_mock = self.probe_patch.start()

        offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        self.relationship = offer
        self.peer_id = self.peer_store.register_peer()
        self.peer_store.bind_relationship(self.peer_id, offer["relationship_id"])

    def tearDown(self):
        self.probe_patch.stop()
        fi.CAPABILITIES.pop(self.capability.capability_id, None)
        self._tmp.cleanup()

    def _signed_request(self, *, authority=None, capability_id=None, peer_id=None, payload=b"governed reachability probe"):
        capability_id = capability_id or self.capability.capability_id
        authority = authority or _authority((self.capability.capability_id,))
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain")
        correlation_id = fi._new_id("CORR")
        xfer = fi.submit_transfer(fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority((capability_id,)),
            correlation_id=correlation_id,
        ), transport)
        assert xfer.transfer_state == fi.TRANSFER_COMPLETED
        unsigned = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id=capability_id, authority_context=authority,
            correlation_id=correlation_id, causation_id=xfer.transfer_id, timeout_seconds=5,
            relationship_id=self.relationship["relationship_id"],
            source_peer_id=peer_id or self.peer_id,
        )
        key = self.key_store.resolve_key(self.relationship["key_id"])
        return transport, env, fi.sign_request(unsigned, key, key_id=self.relationship["key_id"])

    def _process(self, transport, request, **kwargs):
        kwargs.setdefault("reachability_state", INJECTED_REACHABILITY)
        return fi.process_remote_capability_request(
            request, transport, key_store=self.key_store, pairing_store=self.pairing_store,
            peer_store=self.peer_store, replay_guard=self.replay_guard,
            lineage_store=self.lineage_store, **kwargs,
        )

    def _manifest_for(self, env):
        matches = [m for m in LineageStore(self.lineage_root).list_all() if m["source_reference"] == env.envelope_id]
        self.assertEqual(len(matches), 1, "expected exactly one durable lineage manifest for the envelope")
        return matches[0]

    def _assert_refused(self, result, receipt, expected_status):
        self.assertEqual(result.status, expected_status)
        self.assertEqual(receipt.capability_status, expected_status)
        self.assertEqual(receipt.receipt_id, fi.compute_receipt_id(
            receipt.correlation_id, receipt.causation_id, receipt.source_node_id, receipt.destination_node_id,
            receipt.artifact_id, receipt.sha256, receipt.capability_id, receipt.transfer_state, expected_status,
        ))
        self.assertEqual(self.capability.invocation_count, 0)
        self.probe_mock.assert_not_called()


class TestValidRequestExecutesWithDurableReceipt(_GovernedChainTestCase):
    def test_valid_authenticated_request_executes_authorized_harmless_capability(self):
        transport, env, request = self._signed_request()
        result, receipt = self._process(transport, request)

        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(result.structured_result, {"payload_len": len(b"governed reachability probe")})
        self.assertEqual(self.capability.invocation_count, 1)
        self.probe_mock.assert_not_called()

    def test_valid_request_produces_execution_result_and_durable_receipt(self):
        transport, env, request = self._signed_request()
        result, receipt = self._process(transport, request)

        self.assertEqual(receipt.capability_status, fi.CAP_COMPLETED)
        self.assertEqual(receipt.capability_id, self.capability.capability_id)
        self.assertEqual(receipt.artifact_id, env.artifact_id)
        self.assertEqual(receipt.sha256, env.sha256)
        self.assertEqual(receipt.causation_id, request.request_id)
        # receipt != truth/evidence/promotion, even for a successful execution
        self.assertEqual(receipt.truth_status, "RECEIPT_NOT_TRUTH")
        self.assertEqual(receipt.evidence_status, fi.EVIDENCE_STATUS)
        self.assertEqual(receipt.promotion_status, fi.PROMOTION_STATUS)

        # durable: a fresh guard instance over the same root sees the disposition
        durable = fi.RequestReplayGuard(self.replay_root).get(request.request_id)
        self.assertEqual(durable["status"], fi.CAP_COMPLETED)
        self.assertEqual(durable["source_peer_id"], self.peer_id)
        self.assertEqual(durable["relationship_id"], self.relationship["relationship_id"])
        self.assertNotIn("integrity_tag", durable)
        self.assertEqual(durable["sha256"], env.sha256)


class TestRefusalsAreClassifiedAndDoNotExecute(_GovernedChainTestCase):
    def test_invalid_integrity_tag_rejected(self):
        transport, env, request = self._signed_request()
        tampered = fi.replace(request, integrity_tag="0" * 64)
        result, receipt = self._process(transport, tampered)
        self._assert_refused(result, receipt, fi.CAP_FAILED)
        self.assertIn("integrity verification failed", result.error_detail)
        # rejected before replay/authority: nothing durably recorded
        self.assertIsNone(fi.RequestReplayGuard(self.replay_root).get(request.request_id))

    def test_unknown_peer_rejected(self):
        transport, env, request = self._signed_request(peer_id="PEER-" + fi.uuid.uuid4().hex)
        result, receipt = self._process(transport, request)
        self._assert_refused(result, receipt, fi.CAP_FAILED)
        self.assertIn("peer identity verification failed", result.error_detail)

    def test_revoked_pairing_rejected(self):
        transport, env, request = self._signed_request()
        self.pairing_store.revoke(self.relationship["relationship_id"], reason="test: revoked pairing")
        result, receipt = self._process(transport, request)
        self._assert_refused(result, receipt, fi.CAP_FAILED)
        self.assertIn("revoked", result.error_detail)

    def test_expired_authority_rejected(self):
        expired = _authority((self.capability.capability_id,), expires_at=_utc_stamp(timedelta(hours=-1)))
        transport, env, request = self._signed_request(authority=expired)
        result, receipt = self._process(transport, request)
        self._assert_refused(result, receipt, fi.CAP_UNAUTHORIZED)

    def test_unauthorized_capability_rejected(self):
        other_only = _authority(("some_other_capability",))
        transport, env, request = self._signed_request(authority=other_only)
        result, receipt = self._process(transport, request)
        self._assert_refused(result, receipt, fi.CAP_UNAUTHORIZED)

    def test_replay_rejected_without_reexecution(self):
        transport, env, request = self._signed_request()
        first, _ = self._process(transport, request)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        replayed, replay_receipt = self._process(transport, request)
        self.assertEqual(replayed.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(replay_receipt.capability_status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.capability.invocation_count, 1)
        self.probe_mock.assert_not_called()

    def test_failure_produces_correctly_classified_durable_refusal_receipt(self):
        other_only = _authority(("some_other_capability",))
        transport, env, request = self._signed_request(authority=other_only)
        result, receipt = self._process(transport, request)
        self._assert_refused(result, receipt, fi.CAP_UNAUTHORIZED)
        self.assertEqual(receipt.sha256, env.sha256)
        durable = fi.RequestReplayGuard(self.replay_root).get(request.request_id)
        self.assertEqual(durable["status"], fi.CAP_UNAUTHORIZED)
        self.assertIsNone(durable["structured_result"])
        self.assertIn("not authorized", durable["error_detail"])


class TestReachabilityIsExplicitAndSeparateFromAuthority(_GovernedChainTestCase):
    def test_missing_reachability_is_handled_without_external_probing(self):
        transport, env, request = self._signed_request()
        result, _ = self._process(transport, request, reachability_state=None)

        self.probe_mock.assert_not_called()
        manifest = self._manifest_for(env)
        self.assertIsNone(manifest["selected_capability"])
        self.assertTrue(manifest["routing_note"].startswith(ah.REACHABILITY_NOT_SUPPLIED))
        # discovery is not authorization: the authorized capability still runs
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.capability.invocation_count, 1)

    def test_injected_reachability_is_passed_to_the_routing_layer(self):
        transport, env, request = self._signed_request()
        result, _ = self._process(transport, request, reachability_state=INJECTED_REACHABILITY)

        self.probe_mock.assert_not_called()
        manifest = self._manifest_for(env)
        self.assertEqual(manifest["selected_capability"], ROUTABLE_CAPABILITY)
        self.assertIn("selected on routing_score", manifest["routing_note"])
        # routed capability is never executed by routing; dispatch follows request.capability_id
        self.assertEqual(result.capability_id, self.capability.capability_id)
        self.assertEqual(self.capability.invocation_count, 1)

    def test_malformed_reachability_fails_closed_without_probing(self):
        transport, env, request = self._signed_request()
        malformed = {ROUTABLE_CAPABILITY: {"reachability_confidence": "yes"}}
        self._process(transport, request, reachability_state=malformed)

        self.probe_mock.assert_not_called()
        manifest = self._manifest_for(env)
        self.assertIsNone(manifest["selected_capability"])
        self.assertTrue(manifest["routing_note"].startswith(ah.REACHABILITY_MALFORMED))

    def test_reachability_does_not_grant_execution_authority(self):
        reachable = {self.capability.capability_id: {"reachability_confidence": 1.0, "evidence": "fixture"}}
        transport, env, request = self._signed_request(authority=_authority(("some_other_capability",)))
        result, receipt = self._process(transport, request, reachability_state=reachable)
        self._assert_refused(result, receipt, fi.CAP_UNAUTHORIZED)

    def test_reachability_record_is_not_evidence_of_execution(self):
        transport, env, request = self._signed_request()
        _, receipt = self._process(transport, request, reachability_state=INJECTED_REACHABILITY)
        manifest = self._manifest_for(env)
        self.assertEqual(manifest["selected_capability"], ROUTABLE_CAPABILITY)
        self.assertEqual(manifest["execution_status"], ah.EXECUTION_STATUS)
        self.assertEqual(manifest["evidence_status"], ah.EVIDENCE_STATUS)
        self.assertEqual(manifest["promotion_status"], ah.PROMOTION_STATUS)
        self.assertEqual(receipt.evidence_status, fi.EVIDENCE_STATUS)

    def test_live_discovery_runs_only_when_explicitly_authorized(self):
        self.probe_mock.side_effect = None
        self.probe_mock.return_value = dict(INJECTED_REACHABILITY)  # stand-in; no real probe is launched
        transport, env, request = self._signed_request()
        self._process(transport, request, reachability_state=None, allow_live_discovery=True)

        self.probe_mock.assert_called_once_with()
        self.assertEqual(self._manifest_for(env)["selected_capability"], ROUTABLE_CAPABILITY)


class TestRouteToCapabilityContract(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(discover, "probe_all", side_effect=_probe_forbidden)
        self.probe_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_does_not_probe(self):
        selected, note = ah.route_to_capability("text/plain")
        self.assertIsNone(selected)
        self.assertTrue(note.startswith(ah.REACHABILITY_NOT_SUPPLIED))
        self.probe_mock.assert_not_called()

    def test_supplied_state_is_used_verbatim(self):
        selected, _ = ah.route_to_capability("text/plain", reachability_state=INJECTED_REACHABILITY)
        self.assertEqual(selected, ROUTABLE_CAPABILITY)
        self.probe_mock.assert_not_called()

    def test_malformed_shapes_fail_closed(self):
        for bad in ([], {"x": 1}, {"x": {}}, {"x": {"reachability_confidence": True}},
                    {"x": {"reachability_confidence": 1.5}}, {1: {"reachability_confidence": 1.0}}):
            with self.subTest(bad=bad):
                selected, note = ah.route_to_capability("text/plain", reachability_state=bad)
                self.assertIsNone(selected)
                self.assertTrue(note.startswith(ah.REACHABILITY_MALFORMED))
        self.probe_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
