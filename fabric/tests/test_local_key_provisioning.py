"""Tests for FW-LOCAL-KEY-PROVISIONING-CONTRACT-001 (in-process half).

Proves fabric.interface.LocalKeyStore establishes KEY LIFECYCLE (not
peer identity): provisioning, stable key_id reference, ACTIVE/RETIRED/
REVOKED status, hard-cutover rotation, revocation distinct from
rotation, and durability across a fresh store instance standing in for
a process restart -- then proves process_remote_capability_request()'s
key_store parameter correctly resolves request.integrity_key_id and
fails closed for unknown/malformed/retired/revoked keys, without ever
weakening authority or replay.

Discovery finding this file exists to close: FW-MESSAGE-INTEGRITY-
CONTRACT-001 proved HMAC-SHA256 integrity given a TEST-SUPPLIED key, but
established no lifecycle for that key at all -- no key_id, no
provisioning primitive, no rotation, no revocation. No existing
repository structure (searched: key/secret/authkey/credential/token/
keystore/keyring/rotation/revoke/provision/trust/identity/device/peer)
provided this; evidence_envelope.envelope explicitly states "There is no
revocation or replacement" anywhere in its own mission-lifecycle
machinery either. This mission adds the first one.

Stdlib unittest, InMemoryFabricTransport only (no subprocess -- that half
is covered by test_local_key_provisioning_loopback.py / _tcp.py). Spy
capability provider technique established in test_authority_expiry_e2e.py
and reused by every later mission.
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

PC_ID = "PC-NODE-KEYPROV"
PHONE_ID = "PHONE-NODE-KEYPROV"


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


def _transfer_and_build_signed_request(transport, spy, key_store, key_id, key_bytes,
                                        cap_authority=None, payload=b"key-provisioning probe payload", artifact_id=None):
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
    signed = fi.sign_request(unsigned, key_bytes, key_id=key_id) if key_bytes is not None else unsigned
    return env, signed


class _KeyStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.spy = _SpyCapabilityProvider("keyprov_spy_" + fi.uuid.uuid4().hex[:8])
        fi.register_capability(self.spy)
        self._keys_tmp = tempfile.TemporaryDirectory()
        self._replay_tmp = tempfile.TemporaryDirectory()
        self.key_store = fi.LocalKeyStore(Path(self._keys_tmp.name))
        self.replay_guard = fi.RequestReplayGuard(Path(self._replay_tmp.name))

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)
        self._keys_tmp.cleanup()
        self._replay_tmp.cleanup()


class TestKeyStoreLifecyclePrimitives(unittest.TestCase):
    """Pure LocalKeyStore behavior, no transport/request involved."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = fi.LocalKeyStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_provisioned_key_is_active_and_resolvable(self):
        key_id = self.store.provision_key()
        self.assertEqual(self.store.status_of(key_id), fi.KEY_STATUS_ACTIVE)
        self.assertIsNotNone(self.store.resolve_key(key_id))
        self.assertEqual(len(self.store.resolve_key(key_id)), 32)

    def test_rotation_is_hard_cutover(self):
        k1 = self.store.provision_key()
        k2 = self.store.provision_key(supersedes=k1)
        self.assertEqual(self.store.status_of(k1), fi.KEY_STATUS_RETIRED)
        self.assertEqual(self.store.status_of(k2), fi.KEY_STATUS_ACTIVE)
        self.assertIsNone(self.store.resolve_key(k1))  # hard cutover: old key stops resolving immediately
        self.assertIsNotNone(self.store.resolve_key(k2))

    def test_revocation_distinguishable_from_retirement_in_metadata(self):
        k1 = self.store.provision_key()
        k2 = self.store.provision_key(supersedes=k1)  # k1 becomes RETIRED
        self.store.revoke_key(k2, reason="test revoke")
        self.assertEqual(self.store.status_of(k1), fi.KEY_STATUS_RETIRED)
        self.assertEqual(self.store.status_of(k2), fi.KEY_STATUS_REVOKED)
        # Both fail closed identically at resolve_key(), but the metadata
        # ledger keeps them independently observable/auditable.
        self.assertIsNone(self.store.resolve_key(k1))
        self.assertIsNone(self.store.resolve_key(k2))

    def test_revoking_unknown_key_raises(self):
        with self.assertRaises(fi.KeyProvisioningError):
            self.store.revoke_key("IKEY-" + fi.uuid.uuid4().hex)

    def test_superseding_unknown_key_raises(self):
        with self.assertRaises(fi.KeyProvisioningError):
            self.store.provision_key(supersedes="IKEY-" + fi.uuid.uuid4().hex)

    def test_unknown_key_id_fails_closed(self):
        self.assertIsNone(self.store.status_of("IKEY-" + fi.uuid.uuid4().hex))
        self.assertIsNone(self.store.resolve_key("IKEY-" + fi.uuid.uuid4().hex))

    def test_malformed_key_id_fails_closed(self):
        self.assertIsNone(self.store.status_of("not a valid key id!!"))
        self.assertIsNone(self.store.resolve_key("not a valid key id!!"))

    def test_secret_file_has_restrictive_permissions(self):
        import os
        key_id = self.store.provision_key()
        mode = oct(os.stat(self.store._secret_path(key_id)).st_mode)[-3:]
        self.assertEqual(mode, "600")

    def test_lifecycle_state_survives_fresh_store_instance(self):
        k1 = self.store.provision_key()
        k2 = self.store.provision_key(supersedes=k1)
        self.store.revoke_key(k2)
        restarted = fi.LocalKeyStore(Path(self._tmp.name))  # simulates process restart
        self.assertIsNot(restarted, self.store)
        self.assertEqual(restarted.status_of(k1), fi.KEY_STATUS_RETIRED)
        self.assertEqual(restarted.status_of(k2), fi.KEY_STATUS_REVOKED)
        self.assertIsNone(restarted.resolve_key(k1))
        self.assertIsNone(restarted.resolve_key(k2))


class TestActiveKeyValidRequest(_KeyStoreTestCase):
    """Matrix item 1."""

    def test_active_key_signed_request_executes_once(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestUnknownKeyId(_KeyStoreTestCase):
    """Matrix item 2."""

    def test_unknown_key_id_rejected_with_zero_execution(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        fake_secret = fi.secrets.token_bytes(32)
        env, signed = _transfer_and_build_signed_request(
            transport, self.spy, self.key_store, "IKEY-" + fi.uuid.uuid4().hex, fake_secret,
        )
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)


class TestMalformedKeyId(_KeyStoreTestCase):
    """Matrix item 3."""

    def test_malformed_key_id_rejected_with_zero_execution(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        malformed = fi.replace(signed, integrity_key_id="not a valid key id!!")
        result, _ = fi.process_remote_capability_request(malformed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertIn("integrity", result.error_detail.lower())
        self.assertEqual(self.spy.invocation_count, 0)

    def test_missing_key_id_rejected_with_zero_execution(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        no_key_id = fi.replace(signed, integrity_key_id=None)
        result, _ = fi.process_remote_capability_request(no_key_id, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestActiveKeyTamperRejected(_KeyStoreTestCase):
    """Matrix item 4."""

    def test_active_key_but_tampered_content_rejected_with_zero_execution(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        tampered = fi.replace(signed, capability_id="attacker_chosen_capability")  # stale tag
        result, _ = fi.process_remote_capability_request(tampered, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestActiveKeyExpiredAuthority(_KeyStoreTestCase):
    """Matrix item 5 -- KEY ACCEPTANCE and EXECUTION AUTHORITY remain
    orthogonal gates: a cryptographically valid, ACTIVE-key-signed
    request is still denied when authority has expired."""

    def test_active_key_with_expired_authority_rejected_with_zero_execution(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        expired_authority = _authority((self.spy.capability_id,), expires_at="2020-01-01T00:00:00Z")
        env, signed = _transfer_and_build_signed_request(
            transport, self.spy, self.key_store, key_id, key_bytes, cap_authority=expired_authority,
        )
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)  # NOT CAP_FAILED -- integrity passed, authority denied
        self.assertEqual(self.spy.invocation_count, 0)


class TestRevokedKeyOtherwiseValidRequest(_KeyStoreTestCase):
    """Matrix item 6 -- Section 13's central claim: REVOKED KEY + VALID
    AUTHORITY -> ZERO EXECUTION, even though the HMAC is mathematically
    correct under the (now-revoked) key's own bytes."""

    def test_revoked_key_rejected_despite_otherwise_valid_request(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(
            transport, self.spy, self.key_store, key_id, key_bytes,
            cap_authority=_authority((self.spy.capability_id,), expires_at="2099-01-01T00:00:00Z"),
        )
        self.key_store.revoke_key(key_id, reason="test: simulate compromised key")
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestRotatedKeyBehavior(_KeyStoreTestCase):
    """Matrix items 7 & 8 -- rotated (new) key accepted; old key, per the
    documented hard-cutover policy, immediately rejected."""

    def test_new_key_after_rotation_is_accepted(self):
        k1 = self.key_store.provision_key()
        k2 = self.key_store.provision_key(supersedes=k1)
        k2_secret = self.key_store.resolve_key(k2)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, k2, k2_secret)
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

    def test_old_key_after_rotation_is_rejected(self):
        k1 = self.key_store.provision_key()
        k1_secret = self.key_store.resolve_key(k1)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        # Build and sign a request with k1 BEFORE rotating (secret still resolvable at signing time).
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, k1, k1_secret)
        self.key_store.provision_key(supersedes=k1)  # rotate: k1 -> RETIRED, hard cutover
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=self.key_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestProcessRestartKeyLifecycle(_KeyStoreTestCase):
    """Matrix items 9 & 10, in-process proxy (a fresh LocalKeyStore
    instance over the same directory is exactly what a real process
    restart re-creates; the real subprocess restart proof lives in
    test_local_key_provisioning_loopback.py / _tcp.py)."""

    def test_active_key_after_restart_remains_usable(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        restarted_store = fi.LocalKeyStore(Path(self._keys_tmp.name))
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, restarted_store, key_id, key_bytes)
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=restarted_store)
        self.assertEqual(result.status, fi.CAP_COMPLETED)

    def test_revoked_key_after_restart_remains_rejected(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        self.key_store.revoke_key(key_id)
        restarted_store = fi.LocalKeyStore(Path(self._keys_tmp.name))
        result, _ = fi.process_remote_capability_request(signed, transport, key_store=restarted_store)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestSecretAbsenceFromWireAndEvidence(_KeyStoreTestCase):
    """Matrix items 11 & 12 -- secret key bytes must never cross the wire
    or appear in any evidence/result/log-shaped surface. key_id (not
    secret) and integrity_tag (a public digest) are expected and fine."""

    def test_secret_bytes_absent_from_serialized_wire_request(self):
        from fabric.loopback import wire
        import json as _json

        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)

        wire_dict = wire.capability_request_to_wire(signed)
        wire_bytes = _json.dumps(wire_dict).encode("utf-8")

        self.assertNotIn(key_bytes, wire_bytes)
        self.assertNotIn(key_bytes.hex().encode("ascii"), wire_bytes)
        # key_id and integrity_tag ARE expected on the wire -- they are not secret.
        self.assertEqual(wire_dict["integrity_key_id"], key_id)
        self.assertEqual(wire_dict["integrity_tag"], signed.integrity_tag)

    def test_secret_bytes_absent_from_result_receipt_and_replay_ledger(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        result, receipt = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(result.status, fi.CAP_COMPLETED)

        import json as _json
        result_bytes = _json.dumps({
            "request_id": result.request_id, "capability_id": result.capability_id, "status": result.status,
            "structured_result": result.structured_result, "error_detail": result.error_detail,
        }).encode("utf-8")
        self.assertNotIn(key_bytes, result_bytes)
        self.assertNotIn(key_bytes.hex().encode("ascii"), result_bytes)

        receipt_bytes = _json.dumps(receipt.to_dict()).encode("utf-8")
        self.assertNotIn(key_bytes, receipt_bytes)
        self.assertNotIn(key_bytes.hex().encode("ascii"), receipt_bytes)

        stored_disposition = self.replay_guard.get(signed.request_id)
        disposition_bytes = _json.dumps(stored_disposition).encode("utf-8")
        self.assertNotIn(key_bytes, disposition_bytes)
        self.assertNotIn(key_bytes.hex().encode("ascii"), disposition_bytes)


class TestValidDuplicateWithKeyStorePreservesReplaySemantics(_KeyStoreTestCase):
    """Matrix item 13."""

    def test_valid_duplicate_still_suppressed(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        first, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        second, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestHistoricalRequestWithRevokedKey(_KeyStoreTestCase):
    """Matrix item 14 -- documented, deterministic policy: integrity
    verification (now including key resolution) happens BEFORE replay
    resolution, so once a key is revoked, EVEN THE ORIGINAL, otherwise-
    completed request_id can no longer pass verification if replayed --
    historical DISPOSITION RETRIEVAL still requires the presented message
    to currently verify. This is a deliberate, documented choice: the
    replay_guard's own stored disposition is not reachable at all once a
    request's key has been revoked, because integrity is checked first
    on every delivery, not only the first. Zero execution either way."""

    def test_completed_request_replayed_after_its_key_is_revoked_is_rejected_not_duplicated(self):
        key_id = self.key_store.provision_key()
        key_bytes = self.key_store.resolve_key(key_id)
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        env, signed = _transfer_and_build_signed_request(transport, self.spy, self.key_store, key_id, key_bytes)
        first, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        self.key_store.revoke_key(key_id, reason="test: revoked after completion")
        second, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, replay_guard=self.replay_guard,
        )
        self.assertEqual(second.status, fi.CAP_FAILED)
        self.assertNotEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)  # still only the one, original execution


if __name__ == "__main__":
    unittest.main()
