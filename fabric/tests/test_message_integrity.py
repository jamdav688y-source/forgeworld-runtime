"""Tests for FW-MESSAGE-INTEGRITY-CONTRACT-001 (in-process half).

Proves fabric.interface.{sign_request, verify_request_integrity,
compute_request_integrity_tag} establish a MESSAGE INTEGRITY gate for
process_remote_capability_request(): an HMAC-SHA256 tag over every
governance-relevant field of a RemoteCapabilityRequest (request_id,
source/destination node, artifact_id, capability_id, the full
authority_context, correlation_id, causation_id, timeout_seconds,
requested_at), verified in constant time (hmac.compare_digest), BEFORE
replay handling, envelope validation, or authority evaluation.

Discovery finding this file exists to fix: before this mission, nothing
bound these fields together at all. env.sha256 (fabric.interface.
validate_envelope) only ever covered the ARTIFACT PAYLOAD, is an unkeyed
plain digest (anyone can recompute it for any bytes -- it catches
accidental corruption, not deliberate tampering), and says nothing about
request_id/capability_id/authority_context/expires_at. compute_receipt_id
is also unkeyed and computed only on the OUTPUT/receipt side. The
multiprocessing.connection authkey challenge (confirmed by reading
CPython's own deliver_challenge/answer_challenge source) authenticates
the PEER once, AT CONNECTION ESTABLISHMENT, via an HMAC-MD5 challenge --
it says nothing about the integrity of any individual message sent
afterward. None of these three mechanisms is message integrity for a
capability request; this mission adds the first one.

MESSAGE INTEGRITY ONLY: a valid tag proves the signer knew the shared
key, not who the signer is (no peer identity claim), and integrity
verification is a precondition checked BEFORE authority -- a validly
signed, unexpired, in-scope request can still be denied by every
existing check unchanged (proven explicitly by
TestIntegrityDoesNotWeakenExistingChecks below).

Stdlib unittest, InMemoryFabricTransport only (no subprocess -- that half
is covered by test_message_integrity_loopback.py / _tcp.py). Zero-
execution evidence uses the same spy capability provider technique
established in test_authority_expiry_e2e.py and
test_message_identity_replay.py.
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

PC_ID = "PC-NODE-INTEGRITY"
PHONE_ID = "PHONE-NODE-INTEGRITY"

TEST_KEY = b"test-only-integrity-key-not-for-production-use"
WRONG_KEY = b"a-different-test-only-key-attacker-does-not-have-the-real-one"


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


def _transfer_and_build_signed_request(transport, spy, cap_authority=None, key=TEST_KEY,
                                        payload=b"integrity-contract probe payload", artifact_id=None):
    cap_authority = cap_authority or _authority((spy.capability_id,))
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id)
    correlation_id = fi._new_id("CORR")
    xfer_request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=PC_ID, authority_context=_authority((spy.capability_id,)),
        correlation_id=correlation_id,
    )
    xfer_result = fi.submit_transfer(xfer_request, transport)
    assert xfer_result.transfer_state == fi.TRANSFER_COMPLETED
    unsigned = fi.RemoteCapabilityRequest(
        request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
        artifact_id=env.artifact_id, capability_id=spy.capability_id, authority_context=cap_authority,
        correlation_id=correlation_id, causation_id=xfer_result.transfer_id, timeout_seconds=5,
    )
    signed = fi.sign_request(unsigned, key) if key is not None else unsigned
    return env, signed


class _IntegrityTestCase(unittest.TestCase):
    def setUp(self):
        self.spy = _SpyCapabilityProvider("integrity_spy_" + fi.uuid.uuid4().hex[:8])
        fi.register_capability(self.spy)
        self._tmp = tempfile.TemporaryDirectory()
        self.guard = fi.RequestReplayGuard(Path(self._tmp.name))

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)
        self._tmp.cleanup()


class TestValidSignedMessageExecutesOnce(_IntegrityTestCase):
    """Adversarial matrix item 1."""

    def test_untouched_valid_signed_request_executes(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        result, receipt = fi.process_remote_capability_request(signed, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestRequestIdMutationRejected(_IntegrityTestCase):
    """Adversarial matrix item 2."""

    def test_request_id_mutation_fails_integrity_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        tampered = fi.replace(signed, request_id=fi._new_id("CAPREQ"))  # stale tag, new id
        result, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestCapabilityMutationRejected(_IntegrityTestCase):
    """Adversarial matrix item 3."""

    def test_capability_id_mutation_fails_integrity_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        fi.register_capability(_SpyCapabilityProvider("some_other_registered_capability"))
        try:
            env, signed = _transfer_and_build_signed_request(transport, self.spy)
            tampered = fi.replace(signed, capability_id="some_other_registered_capability")
            result, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY)
            self.assertEqual(result.status, fi.CAP_FAILED)
            self.assertIn("integrity", result.error_detail.lower())
            self.assertEqual(self.spy.invocation_count, 0)
        finally:
            fi.CAPABILITIES.pop("some_other_registered_capability", None)


class TestActorMutationRejected(_IntegrityTestCase):
    """Adversarial matrix item 4."""

    def test_actor_id_mutation_fails_integrity_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        mutated_authority = fi.replace(signed.authority_context, actor_id="ATTACKER-CONTROLLED-ACTOR")
        tampered = fi.replace(signed, authority_context=mutated_authority)  # stale tag
        result, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestExpiryMutationRejected(_IntegrityTestCase):
    """Adversarial matrix item 5 -- an attacker EXTENDING expiry without
    the key must be caught by integrity, independent of and prior to
    authority-expiry enforcement itself."""

    def test_expiry_extension_fails_integrity_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(
            transport, self.spy, cap_authority=_authority((self.spy.capability_id,), expires_at="2020-01-01T00:00:00Z"),
        )
        mutated_authority = fi.replace(signed.authority_context, expires_at="2099-01-01T00:00:00Z")  # attacker extends expiry
        tampered = fi.replace(signed, authority_context=mutated_authority)  # stale tag
        result, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestArtifactReferenceMutationRejected(_IntegrityTestCase):
    """Adversarial matrix item 6 (artifact REFERENCE, i.e. artifact_id --
    raw artifact PAYLOAD content tampering is a separate, pre-existing,
    unmodified concern already covered by env.sha256 re-verification)."""

    def test_artifact_id_mutation_fails_integrity_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        # A second, genuinely different artifact, so the mutated artifact_id
        # is not simply nonexistent -- it is a real swap of which artifact
        # this signed request would otherwise have pointed to.
        other_env = fi.build_artifact_envelope(PHONE_ID, b"a different artifact entirely", declared_content_type="text/plain")
        tampered = fi.replace(signed, artifact_id=other_env.artifact_id)  # stale tag
        result, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestTagMutationRejected(_IntegrityTestCase):
    """Adversarial matrix item 7."""

    def test_flipped_tag_character_fails_integrity_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        flipped_char = "0" if signed.integrity_tag[0] != "0" else "1"
        tampered = fi.replace(signed, integrity_tag=flipped_char + signed.integrity_tag[1:])
        result, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestMissingTagPolicy(_IntegrityTestCase):
    """Adversarial matrix item 8 -- explicit compatibility policy: when
    integrity_key IS configured on the receiver, integrity is MANDATORY,
    so a missing tag fails closed exactly like a mismatched one. Only
    when integrity_key is NOT configured (a separate test class below)
    is an unsigned request accepted, preserving full backward
    compatibility."""

    def test_missing_tag_fails_when_integrity_key_is_configured(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        unsigned = fi.replace(signed, integrity_tag=None)
        result, _ = fi.process_remote_capability_request(unsigned, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestMalformedTagRejected(_IntegrityTestCase):
    """Adversarial matrix item 9."""

    def test_malformed_non_hex_tag_fails_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        malformed = fi.replace(signed, integrity_tag="not-a-valid-hex-tag!!")
        result, _ = fi.process_remote_capability_request(malformed, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)

    def test_wrong_key_fails_with_zero_execution(self):
        # Not in the required matrix but directly relevant: a tag valid
        # under a DIFFERENT key must not verify under this receiver's key.
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, key=WRONG_KEY)
        result, _ = fi.process_remote_capability_request(signed, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestValidDuplicatePreservesReplaySemantics(_IntegrityTestCase):
    """Adversarial matrix item 10 -- integrity and replay compose
    correctly: a genuinely valid, unmutated resend is still recognized as
    a duplicate (not merely re-verified and re-executed)."""

    def test_valid_duplicate_still_suppressed_with_integrity_configured(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        first, _ = fi.process_remote_capability_request(signed, transport, integrity_key=TEST_KEY, replay_guard=self.guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        second, _ = fi.process_remote_capability_request(signed, transport, integrity_key=TEST_KEY, replay_guard=self.guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestCompletedRequestIdWithMutatedContentRejected(_IntegrityTestCase):
    """Adversarial matrix item 11 -- Section 12's critical case: an OLD
    TRUSTED request_id carrying NEW UNVERIFIED CONTENT must be rejected
    as tampered, never answered with the historical duplicate
    disposition. Proves integrity verification happens BEFORE replay
    resolution."""

    def test_completed_request_id_replayed_with_mutated_capability_is_rejected_not_duplicated(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        fi.register_capability(_SpyCapabilityProvider("some_other_registered_capability"))
        try:
            env, signed = _transfer_and_build_signed_request(transport, self.spy)
            first, _ = fi.process_remote_capability_request(signed, transport, integrity_key=TEST_KEY, replay_guard=self.guard)
            self.assertEqual(first.status, fi.CAP_COMPLETED)
            self.assertEqual(self.spy.invocation_count, 1)

            # SAME request_id (the "old trusted" identity), capability_id
            # mutated, tag left stale (the attacker cannot resign).
            tampered = fi.replace(signed, capability_id="some_other_registered_capability")
            second, _ = fi.process_remote_capability_request(tampered, transport, integrity_key=TEST_KEY, replay_guard=self.guard)
            self.assertEqual(second.status, fi.CAP_FAILED)
            self.assertNotEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
            self.assertNotEqual(second.status, fi.CAP_DUPLICATE_DENIED)
            self.assertIn("integrity", second.error_detail.lower())
            self.assertEqual(self.spy.invocation_count, 1)  # still 1 -- the tampered resend never executed either
        finally:
            fi.CAPABILITIES.pop("some_other_registered_capability", None)


class TestSerializationRoundTripPreservesIntegrity(_IntegrityTestCase):
    """Adversarial matrix item 12."""

    def test_wire_roundtripped_signed_request_still_verifies(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy)
        wire_dict = wire.capability_request_to_wire(signed)
        reconstructed, reason = wire.safe_capability_request_from_wire(wire_dict)
        self.assertIsNone(reason)
        self.assertIsNot(reconstructed, signed)
        self.assertTrue(fi.verify_request_integrity(reconstructed, TEST_KEY))

        result, _ = fi.process_remote_capability_request(reconstructed, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestIntegrityKeyOmittedPreservesPriorBehavior(_IntegrityTestCase):
    """Backward compatibility / missing-tag policy's other half: an
    unsigned request is accepted exactly as before WHEN the receiver has
    no integrity_key configured at all."""

    def test_unsigned_request_executes_when_no_integrity_key_configured(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, unsigned = _transfer_and_build_signed_request(transport, self.spy, key=None)
        self.assertIsNone(unsigned.integrity_tag)
        result, _ = fi.process_remote_capability_request(unsigned, transport)  # no integrity_key
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestIntegrityDoesNotWeakenExistingChecks(_IntegrityTestCase):
    """A validly signed, unexpired, in-scope request can still be denied
    by authority -- integrity is a precondition, never a substitute."""

    def test_validly_signed_but_unauthorized_request_still_denied(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, cap_authority=_authority(()))  # empty grant
        result, _ = fi.process_remote_capability_request(signed, transport, integrity_key=TEST_KEY)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)


if __name__ == "__main__":
    unittest.main()
