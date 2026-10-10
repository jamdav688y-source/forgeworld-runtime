"""Tests for FW-LOCAL-PAIRING-KEY-ESTABLISHMENT-001 (in-process half).

Proves fabric.interface.PairingStore establishes a bounded, deliberately-
confirmed cryptographic RELATIONSHIP between two existing node_id
strings (fabric.interface.NodeIdentity's own identifier -- reused, not
reinvented), integrating with the already-proven LocalKeyStore rather
than duplicating secret storage, and that process_remote_capability_
request()'s pairing_store parameter correctly resolves
request.relationship_id and fails closed for unknown/malformed/
unconfirmed/replaced/revoked relationships and for a relationship/key
mismatch, without ever weakening authority, replay, or key-lifecycle
enforcement.

Discovery finding this file exists to close: no pair/pairing/peer/
endpoint/relationship/handshake/nonce/session concept existed anywhere
in production code before this mission (searched: fabric/interface.py,
fabric/loopback/, fabric/tcp/) -- only this mission's own prose boundary
comments ("Explicitly NOT: peer identity") in the prior integrity/key
missions. The existing AuthorityContext/LocalKeyStore/RequestReplayGuard
chain answers WHO/WHAT/WHEN but never HOW two endpoints came to share
the trust material that chain depends on. This mission adds the first
answer, scoped explicitly to a LOCAL bounded proof (both "endpoints" in
every test share one on-disk directory, the same rendezvous mechanism
LocalKeyStore's own transport tests already established) -- not a
solution to real cross-network key exchange.

PAIRING IS NOT IDENTITY: relationship_id names a RELATIONSHIP, never a
human or a device. SHARED SECRET != PEER IDENTITY, PAIRING != EXECUTION
AUTHORITY -- proven explicitly below (TestPairingDoesNotWeakenAuthority /
TestPairingDoesNotWeakenReplay / TestKeyRevocationOrthogonalToPairing).

Stdlib unittest, InMemoryFabricTransport only (no subprocess -- that half
is covered by test_local_pairing_loopback.py / _tcp.py). Spy capability
provider technique established in test_authority_expiry_e2e.py and
reused by every later mission.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.transports import InMemoryFabricTransport

PC_ID = "PC-NODE-PAIRING"
PHONE_ID = "PHONE-NODE-PAIRING"


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


class _PairingTestCase(unittest.TestCase):
    def setUp(self):
        self.spy = _SpyCapabilityProvider("pairing_spy_" + fi.uuid.uuid4().hex[:8])
        fi.register_capability(self.spy)
        self._keys_tmp = tempfile.TemporaryDirectory()
        self._pairing_tmp = tempfile.TemporaryDirectory()
        self._replay_tmp = tempfile.TemporaryDirectory()
        self.key_store = fi.LocalKeyStore(Path(self._keys_tmp.name))
        self.pairing_store = fi.PairingStore(Path(self._pairing_tmp.name))
        self.replay_guard = fi.RequestReplayGuard(Path(self._replay_tmp.name))

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)
        self._keys_tmp.cleanup()
        self._pairing_tmp.cleanup()
        self._replay_tmp.cleanup()

    def _confirmed_relationship(self):
        offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        return offer

    def _transfer_and_build_request(self, cap_authority=None, payload=b"pairing probe payload", artifact_id=None):
        cap_authority = cap_authority or _authority((self.spy.capability_id,))
        env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id)
        correlation_id = fi._new_id("CORR")
        xfer_request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority((self.spy.capability_id,)),
            correlation_id=correlation_id,
        )
        xfer_result = fi.submit_transfer(xfer_request, InMemoryFabricTransport(registered_nodes=(PC_ID,)))
        return env, correlation_id

    def _build_signed_request_under(self, relationship, key_bytes=None, cap_authority=None,
                                     payload=b"pairing probe payload", artifact_id=None, transport=None):
        cap_authority = cap_authority or _authority((self.spy.capability_id,))
        transport = transport if transport is not None else InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id)
        correlation_id = fi._new_id("CORR")
        xfer_request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority((self.spy.capability_id,)),
            correlation_id=correlation_id,
        )
        xfer_result = fi.submit_transfer(xfer_request, transport)
        assert xfer_result.transfer_state == fi.TRANSFER_COMPLETED
        unsigned = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id=self.spy.capability_id, authority_context=cap_authority,
            correlation_id=correlation_id, causation_id=xfer_result.transfer_id, timeout_seconds=5,
            relationship_id=relationship["relationship_id"],
        )
        key_bytes = key_bytes if key_bytes is not None else self.key_store.resolve_key(relationship["key_id"])
        signed = fi.sign_request(unsigned, key_bytes, key_id=relationship["key_id"])
        return transport, signed


class TestValidPairingBecomesActive(_PairingTestCase):
    """Matrix item 1."""

    def test_confirmed_pairing_is_active_and_governed_request_executes(self):
        relationship = self._confirmed_relationship()
        self.assertEqual(self.pairing_store.status_of(relationship["relationship_id"]), fi.PAIRING_STATUS_ACTIVE)
        transport, signed = self._build_signed_request_under(relationship)
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestUnconfirmedPairingNotTrusted(_PairingTestCase):
    """Matrix item 2."""

    def test_unconfirmed_offer_is_not_trusted(self):
        offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        self.assertEqual(self.pairing_store.status_of(offer["relationship_id"]), fi.PAIRING_STATUS_PENDING)
        self.assertIsNone(self.pairing_store.resolve_active(offer["relationship_id"]))
        transport, signed = self._build_signed_request_under(offer)
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)

    def test_wrong_sas_confirmation_raises_and_leaves_pending(self):
        offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        with self.assertRaises(fi.PairingConflictError):
            self.pairing_store.confirm(offer["relationship_id"], "wrongsas")
        self.assertEqual(self.pairing_store.status_of(offer["relationship_id"]), fi.PAIRING_STATUS_PENDING)


class TestMalformedPairingOfferRejected(_PairingTestCase):
    """Matrix item 3."""

    def test_malformed_relationship_id_fails_closed(self):
        self.assertIsNone(self.pairing_store.status_of("not a valid relationship id!!"))
        self.assertIsNone(self.pairing_store.resolve_active("not a valid relationship id!!"))

    def test_confirming_malformed_relationship_id_raises(self):
        with self.assertRaises(fi.PairingConflictError):
            self.pairing_store.confirm("not a valid relationship id!!", "12345678")


class TestUnknownRelationshipZeroExecution(_PairingTestCase):
    """Matrix item 4."""

    def test_unknown_relationship_id_rejected_with_zero_execution(self):
        fake_relationship = {"relationship_id": "REL-" + fi.uuid.uuid4().hex, "key_id": self.key_store.provision_key()}
        transport, signed = self._build_signed_request_under(fake_relationship)
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestRevokedRelationshipZeroExecution(_PairingTestCase):
    """Matrix item 5."""

    def test_revoked_relationship_rejected_with_zero_execution(self):
        relationship = self._confirmed_relationship()
        transport, signed = self._build_signed_request_under(relationship)
        self.pairing_store.revoke(relationship["relationship_id"], reason="test: simulate compromised relationship")
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestRestartPersistence(_PairingTestCase):
    """Matrix items 6 & 7, in-process proxy (real subprocess restart proof
    lives in test_local_pairing_loopback.py / _tcp.py)."""

    def test_relationship_survives_fresh_store_instance(self):
        relationship = self._confirmed_relationship()
        restarted = fi.PairingStore(Path(self._pairing_tmp.name))
        self.assertEqual(restarted.status_of(relationship["relationship_id"]), fi.PAIRING_STATUS_ACTIVE)
        self.assertIsNotNone(restarted.resolve_active(relationship["relationship_id"]))

    def test_revocation_survives_fresh_store_instance(self):
        relationship = self._confirmed_relationship()
        self.pairing_store.revoke(relationship["relationship_id"])
        restarted = fi.PairingStore(Path(self._pairing_tmp.name))
        self.assertEqual(restarted.status_of(relationship["relationship_id"]), fi.PAIRING_STATUS_REVOKED)
        self.assertIsNone(restarted.resolve_active(relationship["relationship_id"]))


class TestWrongRelationshipValidKeyRejected(_PairingTestCase):
    """Matrix item 8."""

    def test_valid_key_claimed_under_the_wrong_relationship_is_rejected(self):
        r1 = self._confirmed_relationship()
        r2 = self._confirmed_relationship()
        self.assertNotEqual(r1["key_id"], r2["key_id"])
        # Attacker holds r1's real (ACTIVE, valid) key but claims r2's relationship_id.
        transport, signed = self._build_signed_request_under(r2, key_bytes=self.key_store.resolve_key(r1["key_id"]))
        # signed was built (and its tag computed) with r2's relationship_id and r1's key --
        # but sign_request() was called with integrity_key_id=r2["key_id"] by _build_signed_request_under's
        # default key_id plumbing; force the mismatch explicitly to model "presents r1's key under r2's claim":
        tampered = fi.replace(signed, integrity_key_id=r1["key_id"])
        result, _ = fi.process_remote_capability_request(
            tampered, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestKeyRevocationOrthogonalToPairing(_PairingTestCase):
    """Matrix item 9 -- relationship ACTIVE and correctly bound, but its
    key is separately revoked in LocalKeyStore: relationship and key
    lifecycle remain orthogonal, exactly as documented."""

    def test_valid_relationship_with_separately_revoked_key_is_rejected(self):
        relationship = self._confirmed_relationship()
        transport, signed = self._build_signed_request_under(relationship)
        self.key_store.revoke_key(relationship["key_id"], reason="test: revoke the bound key directly")
        self.assertEqual(self.pairing_store.status_of(relationship["relationship_id"]), fi.PAIRING_STATUS_ACTIVE)
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestPairingDoesNotWeakenAuthority(_PairingTestCase):
    """Matrix item 10."""

    def test_valid_relationship_with_expired_authority_is_denied_not_failed(self):
        relationship = self._confirmed_relationship()
        expired_authority = _authority((self.spy.capability_id,), expires_at="2020-01-01T00:00:00Z")
        transport, signed = self._build_signed_request_under(relationship, cap_authority=expired_authority)
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)  # pairing/integrity passed, authority denied
        self.assertEqual(self.spy.invocation_count, 0)


class TestTamperedMessageRejected(_PairingTestCase):
    """Matrix item 11."""

    def test_tampered_message_under_valid_relationship_is_rejected(self):
        relationship = self._confirmed_relationship()
        transport, signed = self._build_signed_request_under(relationship)
        tampered = fi.replace(signed, capability_id="attacker_chosen_capability")  # stale tag
        result, _ = fi.process_remote_capability_request(
            tampered, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestPairingDoesNotWeakenReplay(_PairingTestCase):
    """Matrix item 12."""

    def test_duplicate_request_under_valid_relationship_executes_at_most_once(self):
        relationship = self._confirmed_relationship()
        transport, signed = self._build_signed_request_under(relationship)
        first, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        second, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestRePairAfterRevocation(_PairingTestCase):
    """Matrix item 13 -- an old REVOKED relationship must not silently
    become trusted because a new, unrelated pairing occurred; separately,
    re_pair()'s own REPLACED-generation semantics are demonstrated."""

    def test_revoked_relationship_stays_revoked_after_a_fresh_unrelated_pairing(self):
        old_relationship = self._confirmed_relationship()
        self.pairing_store.revoke(old_relationship["relationship_id"], reason="test: compromised")
        new_offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        self.pairing_store.confirm(new_offer["relationship_id"], new_offer["sas"])

        self.assertEqual(self.pairing_store.status_of(old_relationship["relationship_id"]), fi.PAIRING_STATUS_REVOKED)
        self.assertIsNone(self.pairing_store.resolve_active(old_relationship["relationship_id"]))
        self.assertEqual(self.pairing_store.status_of(new_offer["relationship_id"]), fi.PAIRING_STATUS_ACTIVE)

        transport, signed_with_old = self._build_signed_request_under(old_relationship)
        result, _ = fi.process_remote_capability_request(
            signed_with_old, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)

    def test_re_pair_creates_a_distinguishable_replaced_generation(self):
        relationship = self._confirmed_relationship()
        new_offer = self.pairing_store.re_pair(relationship["relationship_id"], PC_ID, PHONE_ID, self.key_store)
        self.assertEqual(self.pairing_store.status_of(relationship["relationship_id"]), fi.PAIRING_STATUS_REPLACED)
        self.assertNotEqual(fi.PAIRING_STATUS_REPLACED, fi.PAIRING_STATUS_REVOKED)  # distinguishable generation, not conflated with revocation
        self.assertEqual(self.pairing_store.status_of(new_offer["relationship_id"]), fi.PAIRING_STATUS_PENDING)
        self.pairing_store.confirm(new_offer["relationship_id"], new_offer["sas"])
        self.assertEqual(self.pairing_store.status_of(new_offer["relationship_id"]), fi.PAIRING_STATUS_ACTIVE)


class TestSecretAbsenceFromEvidenceAndWire(_PairingTestCase):
    """Matrix items 14 & 15."""

    def test_secret_absent_from_pairing_store_metadata_and_offer_result(self):
        relationship = self._confirmed_relationship()
        secret = self.key_store.resolve_key(relationship["key_id"])

        ledger_text = self.pairing_store.ledger_path.read_text()
        self.assertNotIn(secret.hex(), ledger_text)

        offer_repr = json.dumps(relationship).encode("utf-8")
        self.assertNotIn(secret, offer_repr)
        self.assertNotIn(secret.hex().encode("ascii"), offer_repr)

    def test_secret_absent_from_serialized_wire_request(self):
        from fabric.loopback import wire

        relationship = self._confirmed_relationship()
        secret = self.key_store.resolve_key(relationship["key_id"])
        transport, signed = self._build_signed_request_under(relationship)

        wire_dict = wire.capability_request_to_wire(signed)
        wire_bytes = json.dumps(wire_dict).encode("utf-8")
        self.assertNotIn(secret, wire_bytes)
        self.assertNotIn(secret.hex().encode("ascii"), wire_bytes)
        # relationship_id and key_id ARE expected on the wire -- not secret.
        self.assertEqual(wire_dict["relationship_id"], relationship["relationship_id"])
        self.assertEqual(wire_dict["integrity_key_id"], relationship["key_id"])


class TestPairingStoreOmittedPreservesPriorBehavior(_PairingTestCase):
    """Backward compatibility: pairing_store is optional and defaults to
    None. Without it, key_store-only verification behaves exactly as the
    prior mission proved."""

    def test_omitting_pairing_store_falls_back_to_key_store_only_path(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        env = fi.build_artifact_envelope(PHONE_ID, b"fallback probe", declared_content_type="text/plain")
        correlation_id = fi._new_id("CORR")
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        xfer_request = fi.TransferRequest(
            request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
            destination_node_id=PC_ID, authority_context=_authority((self.spy.capability_id,)),
            correlation_id=correlation_id,
        )
        xfer_result = fi.submit_transfer(xfer_request, transport)
        unsigned = fi.RemoteCapabilityRequest(
            request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
            artifact_id=env.artifact_id, capability_id=self.spy.capability_id,
            authority_context=_authority((self.spy.capability_id,)),
            correlation_id=correlation_id, causation_id=xfer_result.transfer_id, timeout_seconds=5,
        )
        signed = fi.sign_request(unsigned, key_bytes, key_id=key_id)  # no relationship_id at all
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)  # no pairing_store
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


if __name__ == "__main__":
    unittest.main()
