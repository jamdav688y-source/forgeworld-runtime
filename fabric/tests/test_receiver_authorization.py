"""Tests for MISSION: FW-PHASE-0-IMPLEMENT-001 -- receiver-held capability
authorization.

Before this mission, process_remote_capability_request() authorized from
the request's own AuthorityContext, which the requester writes and signs:
a correctly paired peer could re-sign an expired grant with
expires_at=None, or invent a grant for any capability, and execute. In
governed mode (pairing_store + peer_store + grant_store) execution now
requires an active grant in the receiver's own LocalGrantStore for the
exact (peer_id, relationship_id, capability_id); the requester's context
can only narrow it.

Stdlib unittest, InMemoryFabricTransport only. discover.probe_all is
patched to raise so no test can trigger live discovery. The receiver's
clock is advanced by patching fabric.interface.datetime, never by sleeping.
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

from capabilities import discover  # noqa: E402
from evidence_envelope import envelope  # noqa: E402
from fabric import interface as fi  # noqa: E402
from fabric.transports import InMemoryFabricTransport  # noqa: E402

PC_ID = "PC-NODE-GRANTS"
PHONE_ID = "PHONE-NODE-GRANTS"


def _stamp(delta):
    return (datetime.now(timezone.utc) + delta).strftime(fi._TIMESTAMP_FORMAT)


def _authority(capability_ids, expires_at=None, actor=PHONE_ID, granted_by="test_policy"):
    return fi.AuthorityContext(
        actor_id=actor, granted_capability_ids=tuple(capability_ids),
        granted_by=granted_by, expires_at=expires_at,
    )


def _receiver_clock_advanced(delta):
    """Patch the receiver's clock (fabric.interface.datetime) forward."""
    class _AdvancedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + delta
    return mock.patch.object(fi, "datetime", _AdvancedDatetime)


class _Spy:
    def __init__(self, prefix):
        self.capability_id = f"{prefix}_{fi.uuid.uuid4().hex[:8]}"
        self.invocation_count = 0

    def invoke(self, manifest_dict, payload):
        self.invocation_count += 1
        return (fi.CAP_COMPLETED, {"payload_len": len(payload)}, None)


class _GrantTestCase(unittest.TestCase):
    def setUp(self):
        self.spy = _Spy("grant_spy")
        self.other_spy = _Spy("grant_other")
        fi.register_capability(self.spy)
        fi.register_capability(self.other_spy)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.key_store = fi.LocalKeyStore(root / "keys")
        self.pairing_store = fi.PairingStore(root / "pairing")
        self.peer_store = fi.PeerIdentityStore(root / "peers")
        self.grants_root = root / "grants"
        self.grant_store = fi.LocalGrantStore(self.grants_root)
        self.replay_root = root / "replay"
        self.replay_guard = fi.RequestReplayGuard(self.replay_root)
        probe = mock.patch.object(discover, "probe_all", side_effect=AssertionError("live discovery attempted"))
        probe.start()
        self.addCleanup(probe.stop)

        self.relationship = self._confirmed_relationship()
        self.peer_id = self._bound_peer(self.relationship)

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)
        fi.CAPABILITIES.pop(self.other_spy.capability_id, None)
        self._tmp.cleanup()

    def _confirmed_relationship(self):
        offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        return offer

    def _bound_peer(self, relationship):
        peer_id = self.peer_store.register_peer()
        self.peer_store.bind_relationship(peer_id, relationship["relationship_id"])
        return peer_id

    def _grant(self, capability_ids=None, peer_id=None, relationship=None, expires_in=timedelta(hours=1)):
        return self.grant_store.issue_grant(
            peer_id or self.peer_id, (relationship or self.relationship)["relationship_id"],
            capability_ids or [self.spy.capability_id], _stamp(expires_in), issued_by="test_operator",
        )

    def _signed(self, *, capability_id=None, authority=None, peer_id=None, relationship=None):
        capability_id = capability_id or self.spy.capability_id
        relationship = relationship or self.relationship
        authority = authority or _authority((capability_id,))
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env = fi.build_artifact_envelope(PHONE_ID, b"grant probe", declared_content_type="text/plain")
        correlation_id = fi._new_id("CORR")
        xfer = fi.submit_transfer(fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=authority, correlation_id=correlation_id,
        ), transport)
        assert xfer.transfer_state == fi.TRANSFER_COMPLETED
        unsigned = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id=capability_id, authority_context=authority,
            correlation_id=correlation_id, causation_id=xfer.transfer_id, timeout_seconds=5,
            relationship_id=relationship["relationship_id"], source_peer_id=peer_id or self.peer_id,
        )
        key = self.key_store.resolve_key(relationship["key_id"])
        return transport, fi.sign_request(unsigned, key, key_id=relationship["key_id"])

    def _process(self, transport, request, **overrides):
        kwargs = dict(
            key_store=self.key_store, pairing_store=self.pairing_store, peer_store=self.peer_store,
            grant_store=self.grant_store, replay_guard=self.replay_guard,
        )
        kwargs.update(overrides)
        return fi.process_remote_capability_request(request, transport, **kwargs)

    def _redeliver(self, transport, request):
        """Put the request's envelope back so the same request can be resent."""
        env = fi.build_artifact_envelope(PHONE_ID, b"grant probe", declared_content_type="text/plain",
                                         artifact_id=request.artifact_id)
        transport.deliver(PC_ID, env)

    def assertDenied(self, result, receipt, code, request=None):
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(receipt.capability_status, fi.CAP_UNAUTHORIZED)
        self.assertIn(f"{fi.RECEIVER_AUTHORIZATION_DENIED}:{code}", result.error_detail)
        if request is not None:
            durable = fi.RequestReplayGuard(self.replay_root).get(request.request_id)
            self.assertEqual(durable["status"], fi.CAP_UNAUTHORIZED)
            self.assertEqual(durable["authorization_code"], code)

    def assertNoExecution(self):
        self.assertEqual(self.spy.invocation_count, 0)
        self.assertEqual(self.other_spy.invocation_count, 0)


class TestGrantedExecution(_GrantTestCase):
    def test_t1_valid_grant_executes_once_with_durable_grant_attribution(self):
        grant_id = self._grant()
        transport, request = self._signed()
        result, receipt = self._process(transport, request)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(receipt.capability_status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)
        durable = fi.RequestReplayGuard(self.replay_root).get(request.request_id)
        self.assertEqual(durable["grant_id"], grant_id)
        self.assertEqual(durable["authorization_code"], fi.GRANT_ACTIVE)
        # receipt states and identifiers unchanged; receipts are not evidence
        self.assertIn(receipt.capability_status, fi._CAP_STATES)
        self.assertTrue(receipt.receipt_id.startswith("RCPT-"))
        self.assertEqual(receipt.evidence_status, fi.EVIDENCE_STATUS)
        self.assertEqual(receipt.promotion_status, fi.PROMOTION_STATUS)

    def test_t19_requester_may_narrow_to_a_subset_of_the_grant(self):
        self._grant([self.spy.capability_id, self.other_spy.capability_id])
        transport, request = self._signed(authority=_authority((self.spy.capability_id,)))
        result, _ = self._process(transport, request)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestMissingAndForgedAuthority(_GrantTestCase):
    def test_t2_no_grant_is_refused_and_recorded(self):
        transport, request = self._signed()
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.NO_ACTIVE_GRANT, request)
        self.assertNoExecution()

    def test_t5_self_widened_capability_is_refused(self):
        self._grant([self.spy.capability_id])
        widened = _authority((self.spy.capability_id, self.other_spy.capability_id))
        transport, request = self._signed(capability_id=self.other_spy.capability_id, authority=widened)
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.CAPABILITY_NOT_GRANTED, request)
        self.assertNoExecution()

    def test_t6_fabricated_grant_from_authenticated_peer_is_refused(self):
        fabricated = _authority((self.spy.capability_id,), actor="anyone", granted_by="self")
        transport, request = self._signed(authority=fabricated)
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.NO_ACTIVE_GRANT, request)
        self.assertNoExecution()

    def test_t9_grant_for_a_different_peer_is_not_usable(self):
        self._grant()
        other_peer = self._bound_peer(self.relationship)
        transport, request = self._signed(peer_id=other_peer)
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.NO_ACTIVE_GRANT, request)
        self.assertNoExecution()

    def test_t8_grant_under_another_relationship_is_a_mismatch(self):
        self._grant()  # bound to self.relationship
        relationship_b = self._confirmed_relationship()
        self.peer_store.bind_relationship(self.peer_id, relationship_b["relationship_id"])
        transport, request = self._signed(relationship=relationship_b)
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.GRANT_RELATIONSHIP_MISMATCH, request)
        self.assertNoExecution()

    def test_t21_reachability_without_a_grant_is_refused(self):
        reachable = {self.spy.capability_id: {"reachability_confidence": 1.0, "evidence": "fixture"}}
        transport, request = self._signed()
        result, receipt = self._process(transport, request, reachability_state=reachable)
        self.assertDenied(result, receipt, fi.NO_ACTIVE_GRANT)
        self.assertNoExecution()


class TestExpiry(_GrantTestCase):
    def test_t3_expired_grant_is_refused(self):
        self._grant(expires_in=timedelta(minutes=5))
        transport, request = self._signed()
        with _receiver_clock_advanced(timedelta(minutes=10)):
            result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.GRANT_EXPIRED, request)
        self.assertNoExecution()

    def test_t4_expiry_bypass_by_resigning_without_expiry_is_refused(self):
        self._grant(expires_in=timedelta(minutes=5))
        never_expiring = _authority((self.spy.capability_id,), expires_at=None)
        transport, request = self._signed(authority=never_expiring)
        with _receiver_clock_advanced(timedelta(minutes=10)):
            result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.GRANT_EXPIRED, request)
        self.assertNoExecution()

    def test_t18_requester_narrowed_expiry_in_the_past_is_refused(self):
        self._grant()
        narrowed = _authority((self.spy.capability_id,), expires_at=_stamp(timedelta(hours=-1)))
        transport, request = self._signed(authority=narrowed)
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.REQUESTER_CONTEXT_DENIED, request)
        self.assertNoExecution()


class TestRevocationAndReplay(_GrantTestCase):
    def test_t7_revoked_grant_is_refused(self):
        grant_id = self._grant()
        self.grant_store.revoke_grant(grant_id, reason="test")
        transport, request = self._signed()
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.GRANT_REVOKED, request)
        self.assertNoExecution()

    def test_t10_replay_after_revocation_returns_original_disposition_without_execution(self):
        grant_id = self._grant()
        transport, request = self._signed()
        first, _ = self._process(transport, request)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.grant_store.revoke_grant(grant_id, reason="test")
        self._redeliver(transport, request)
        replayed, receipt = self._process(transport, request)
        self.assertEqual(replayed.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(receipt.capability_status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

    def test_t11_new_request_after_revocation_is_refused(self):
        grant_id = self._grant()
        transport, request = self._signed()
        first, _ = self._process(transport, request)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.grant_store.revoke_grant(grant_id, reason="test")
        transport2, request2 = self._signed()
        result, receipt = self._process(transport2, request2)
        self.assertDenied(result, receipt, fi.GRANT_REVOKED, request2)
        self.assertEqual(self.spy.invocation_count, 1)

    def test_t14_revocation_and_grants_survive_a_fresh_store_instance(self):
        revoked_id = self._grant([self.spy.capability_id])
        self._grant([self.other_spy.capability_id])
        self.grant_store.revoke_grant(revoked_id, reason="test")
        restarted = fi.LocalGrantStore(self.grants_root)

        transport, request = self._signed()
        result, receipt = self._process(transport, request, grant_store=restarted)
        self.assertDenied(result, receipt, fi.GRANT_REVOKED)
        transport2, request2 = self._signed(capability_id=self.other_spy.capability_id)
        result2, _ = self._process(transport2, request2, grant_store=restarted)
        self.assertEqual(result2.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 0)
        self.assertEqual(self.other_spy.invocation_count, 1)


class TestUnavailableOrCorruptGrantStore(_GrantTestCase):
    def test_t12_corrupt_journal_fails_closed(self):
        self._grant()
        for corruption in ("truncated", "invalid_json"):
            with self.subTest(corruption=corruption):
                data = self.grant_store.ledger_path.read_text(encoding="utf-8")
                if corruption == "truncated":
                    self.grant_store.ledger_path.write_text(data.rstrip("\n"), encoding="utf-8")
                else:
                    self.grant_store.ledger_path.write_text(data + "{not json\n", encoding="utf-8")
                transport, request = self._signed()
                result, receipt = self._process(transport, request)
                self.assertDenied(result, receipt, fi.GRANT_STORE_CORRUPT, request)
                self.assertNoExecution()
                self.grant_store.ledger_path.write_text(data, encoding="utf-8")

    def test_t13_unreadable_store_fails_closed(self):
        self._grant()
        self.grant_store.ledger_path.unlink()
        self.grant_store.ledger_path.mkdir()  # opening a directory raises OSError
        transport, request = self._signed()
        result, receipt = self._process(transport, request)
        self.assertDenied(result, receipt, fi.GRANT_STORE_UNAVAILABLE, request)
        self.assertNoExecution()


class TestGovernedConfiguration(_GrantTestCase):
    def _assert_config_refusal(self, code, **overrides):
        self._grant()
        transport, request = self._signed()
        result, receipt = self._process(transport, request, **overrides)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn(f"{fi.RECEIVER_AUTHORIZATION_CONFIG}:{code}", result.error_detail)
        self.assertNoExecution()
        self.assertIsNone(fi.RequestReplayGuard(self.replay_root).get(request.request_id))

    def test_t15_pairing_without_grant_store_fails_closed(self):
        self._assert_config_refusal(fi.GRANT_STORE_REQUIRED, grant_store=None)

    def test_t16_pairing_without_peer_store_fails_closed(self):
        self._assert_config_refusal(fi.PEER_STORE_REQUIRED, peer_store=None)

    def test_t17_grant_store_without_pairing_and_peer_stores_fails_closed(self):
        self._assert_config_refusal(fi.GOVERNED_STORES_REQUIRED, pairing_store=None, peer_store=None)


class TestOrderingAndDispatch(_GrantTestCase):
    def test_t20_integrity_failure_is_refused_before_grant_evaluation(self):
        self._grant()
        transport, request = self._signed()
        tampered = fi.replace(request, integrity_tag="0" * 64)
        with mock.patch.object(self.grant_store, "evaluate", wraps=self.grant_store.evaluate) as evaluate:
            result, _ = self._process(transport, tampered)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity verification failed", result.error_detail)
        evaluate.assert_not_called()
        self.assertIsNone(fi.RequestReplayGuard(self.replay_root).get(request.request_id))
        self.assertNoExecution()

    def test_t22_grant_for_unregistered_capability_does_not_execute(self):
        unregistered = "unregistered_capability_" + fi.uuid.uuid4().hex[:8]
        self._grant([unregistered])
        transport, request = self._signed(capability_id=unregistered)
        result, _ = self._process(transport, request)
        self.assertEqual(result.status, fi.CAP_UNSUPPORTED)
        self.assertNoExecution()


class TestGrantStoreContract(_GrantTestCase):
    def test_t23_issuance_validation(self):
        rel = self.relationship["relationship_id"]
        cap = [self.spy.capability_id]
        bad_calls = {
            "missing expiry": dict(expires_at=None),
            "past expiry": dict(expires_at=_stamp(timedelta(seconds=-1))),
            "malformed expiry": dict(expires_at="tomorrow"),
            "empty capabilities": dict(capability_ids=[]),
            "string capabilities": dict(capability_ids=self.spy.capability_id),
            "duplicate capabilities": dict(capability_ids=cap + cap),
            "invalid capability id": dict(capability_ids=["../escape"]),
            "invalid peer id": dict(peer_id="not a valid id!"),
            "empty issuer": dict(issued_by=" "),
        }
        for label, override in bad_calls.items():
            with self.subTest(label):
                args = dict(peer_id=self.peer_id, relationship_id=rel, capability_ids=cap,
                            expires_at=_stamp(timedelta(hours=1)), issued_by="test_operator")
                args.update(override)
                with self.assertRaises(fi.GrantStoreError):
                    self.grant_store.issue_grant(**args)
        self.assertEqual(self.grant_store.list_for(self.peer_id, rel), ())

    def test_t24_conflicting_grant_id_is_refused(self):
        existing = self._grant()
        with mock.patch.object(fi, "_new_id", return_value=existing):
            with self.assertRaises(fi.GrantConflictError):
                self._grant([self.other_spy.capability_id])
        self.assertEqual(self.grant_store.status_of(existing)["capability_ids"], [self.spy.capability_id])

    def test_revocation_is_idempotent_append_only_and_unknown_grants_raise(self):
        grant_id = self._grant()
        self.grant_store.revoke_grant(grant_id, reason="first")
        self.grant_store.revoke_grant(grant_id, reason="second")
        records = self.grant_store._read_all()
        self.assertEqual([r["event"] for r in records], [fi.GRANT_EVENT_ISSUED, fi.GRANT_EVENT_REVOKED])
        self.assertEqual(records[1]["peer_id"], self.peer_id)
        with self.assertRaises(fi.GrantStoreError):
            self.grant_store.revoke_grant("GRANT-" + fi.uuid.uuid4().hex)

    def test_grant_ledger_contains_no_key_material(self):
        self._grant()
        secret_hex = self.key_store.resolve_key(self.relationship["key_id"]).hex()
        ledger_text = self.grant_store.ledger_path.read_text(encoding="utf-8")
        self.assertNotIn(secret_hex, ledger_text)
        self.assertNotIn(self.relationship["sas"], ledger_text)

    def test_evaluate_requires_an_aware_time(self):
        with self.assertRaises(fi.FabricError):
            self.grant_store.evaluate(self.peer_id, self.relationship["relationship_id"],
                                      self.spy.capability_id, datetime.now())


if __name__ == "__main__":
    unittest.main()
