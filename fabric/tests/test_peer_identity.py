"""Tests for FW-PEER-IDENTITY-CONTRACT-001 (in-process half).

Proves fabric.interface.PeerIdentityStore establishes a durable,
protocol-level PEER IDENTITY -- deliberately distinct from a pairing
relationship (fabric.interface.PairingStore), a key (LocalKeyStore), an
authority principal (AuthorityContext.actor_id), or a transport-routing
node (NodeIdentity.node_id) -- and that process_remote_capability_
request()'s peer_store parameter correctly resolves
request.source_peer_id, enforces that the resolved peer is currently
bound to the relationship the request arrived under, and fails closed
for unknown/malformed/revoked peers and for peer/relationship mismatch,
all evaluated strictly AFTER message integrity is proven and strictly
BEFORE replay/authority/execution.

Discovery finding this file exists to close: no peer/principal/issuer/
credential concept existed anywhere in production code. Two existing
fields were examined and explicitly REJECTED as substitutes (documented
directly in fabric/interface.py's own module comments): NodeIdentity.
node_id is a transient, unpersisted, unrevocable transport-routing
identifier, not a durable governed principal; AuthorityContext.actor_id
is a free-text authority-attribution string with no lifecycle of its
own. peer_id and actor_id remain semantically INDEPENDENT here (proven
explicitly by TestActorIdRemainsIndependent below) -- this mission never
equates them.

PEER IDENTITY IS NOT AUTHORITY: proven explicitly by
TestPeerIdentityDoesNotWeakenAuthority (expired authority still denies)
and TestMissingCapabilityGrantStillDenied (an empty grant still denies),
even for a fully valid, ACTIVE, correctly-bound peer.

Stdlib unittest, InMemoryFabricTransport only (no subprocess -- that half
is covered by test_peer_identity_loopback.py / _tcp.py). Spy capability
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

PC_ID = "PC-NODE-PEERID"
PHONE_ID = "PHONE-NODE-PEERID"


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


class _PeerIdentityTestCase(unittest.TestCase):
    def setUp(self):
        self.spy = _SpyCapabilityProvider("peerid_spy_" + fi.uuid.uuid4().hex[:8])
        fi.register_capability(self.spy)
        self._keys_tmp = tempfile.TemporaryDirectory()
        self._pairing_tmp = tempfile.TemporaryDirectory()
        self._peers_tmp = tempfile.TemporaryDirectory()
        self._replay_tmp = tempfile.TemporaryDirectory()
        self.key_store = fi.LocalKeyStore(Path(self._keys_tmp.name))
        self.pairing_store = fi.PairingStore(Path(self._pairing_tmp.name))
        self.peer_store = fi.PeerIdentityStore(Path(self._peers_tmp.name))
        self.replay_guard = fi.RequestReplayGuard(Path(self._replay_tmp.name))

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)
        self._keys_tmp.cleanup()
        self._pairing_tmp.cleanup()
        self._peers_tmp.cleanup()
        self._replay_tmp.cleanup()

    def _confirmed_relationship(self):
        offer = self.pairing_store.create_offer(PC_ID, PHONE_ID, self.key_store)
        self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        return offer

    def _peer_bound_to(self, relationship):
        peer_id = self.peer_store.register_peer()
        self.peer_store.bind_relationship(peer_id, relationship["relationship_id"])
        return peer_id

    def _build_signed_request(self, relationship, peer_id, cap_authority=None,
                               payload=b"peer identity probe payload", artifact_id=None):
        cap_authority = cap_authority or _authority((self.spy.capability_id,))
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
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
            relationship_id=relationship["relationship_id"], source_peer_id=peer_id,
        )
        key_bytes = self.key_store.resolve_key(relationship["key_id"])
        signed = fi.sign_request(unsigned, key_bytes, key_id=relationship["key_id"])
        return transport, signed

    def _process(self, transport, signed, **kwargs):
        return fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
            peer_store=self.peer_store, **kwargs,
        )


class TestFullChainExecutesOnce(_PeerIdentityTestCase):
    """Matrix item 1."""

    def test_active_peer_active_relationship_valid_key_valid_authority_executes_once(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestUnknownPeerZeroExecution(_PeerIdentityTestCase):
    """Matrix item 2."""

    def test_unknown_peer_id_rejected_with_zero_execution(self):
        relationship = self._confirmed_relationship()
        fake_peer_id = "PEER-" + fi.uuid.uuid4().hex
        transport, signed = self._build_signed_request(relationship, fake_peer_id)
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestMalformedPeerZeroExecution(_PeerIdentityTestCase):
    """Matrix item 3."""

    def test_malformed_peer_id_rejected_with_zero_execution(self):
        relationship = self._confirmed_relationship()
        transport, signed = self._build_signed_request(relationship, "not a valid peer id!!")
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)

    def test_missing_peer_id_rejected_when_peer_store_configured(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        no_peer = fi.replace(signed, source_peer_id=None)  # stale tag: signed WITH a peer_id, now stripped
        result, _ = self._process(transport, no_peer)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestRevokedPeerZeroExecution(_PeerIdentityTestCase):
    """Matrix item 4."""

    def test_revoked_peer_rejected_with_zero_execution(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        self.peer_store.revoke_peer(peer_id, reason="test: simulate compromised peer")
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestWrongRelationshipZeroExecution(_PeerIdentityTestCase):
    """Matrix item 5."""

    def test_active_peer_not_bound_to_this_relationship_rejected(self):
        relationship_a = self._confirmed_relationship()
        relationship_b = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship_a)  # bound to A, not B
        # Build a request that is genuinely valid (integrity-wise) under
        # relationship B, but claims peer_id which is only bound to A.
        transport, signed = self._build_signed_request(relationship_b, peer_id)
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestRevokedRelationshipZeroExecution(_PeerIdentityTestCase):
    """Matrix item 6 -- relationship resolution already fails before peer
    identity is even reached, but the end-to-end outcome must still be
    zero execution with an ACTIVE, correctly-bound peer."""

    def test_active_peer_with_revoked_relationship_rejected(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        self.pairing_store.revoke(relationship["relationship_id"])
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestRevokedKeyZeroExecution(_PeerIdentityTestCase):
    """Matrix item 7."""

    def test_active_peer_with_revoked_key_rejected(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        self.key_store.revoke_key(relationship["key_id"])
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestPeerIdentityDoesNotWeakenAuthority(_PeerIdentityTestCase):
    """Matrix item 8."""

    def test_active_peer_with_expired_authority_denied_not_failed(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        expired = _authority((self.spy.capability_id,), expires_at="2020-01-01T00:00:00Z")
        transport, signed = self._build_signed_request(relationship, peer_id, cap_authority=expired)
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)  # identity/integrity passed, authority denied
        self.assertEqual(self.spy.invocation_count, 0)


class TestMissingCapabilityGrantStillDenied(_PeerIdentityTestCase):
    """Matrix item 9."""

    def test_active_peer_with_empty_grant_denied_not_failed(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        empty_grant = _authority(())
        transport, signed = self._build_signed_request(relationship, peer_id, cap_authority=empty_grant)
        result, _ = self._process(transport, signed)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestPeerTamperRejected(_PeerIdentityTestCase):
    """Matrix item 10."""

    def test_mutated_peer_id_after_signing_fails_integrity(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        other_peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        tampered = fi.replace(signed, source_peer_id=other_peer_id)  # stale tag
        result, _ = self._process(transport, tampered)
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestReplaySemanticsUnchanged(_PeerIdentityTestCase):
    """Matrix item 11."""

    def test_valid_peer_request_replay_executes_at_most_once(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        first, _ = self._process(transport, signed, replay_guard=self.replay_guard)
        self.assertEqual(first.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

        second, _ = self._process(transport, signed, replay_guard=self.replay_guard)
        self.assertEqual(second.status, fi.CAP_DUPLICATE_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestRestartPersistence(_PeerIdentityTestCase):
    """Matrix items 12 & 13, in-process proxy (real subprocess restart
    proof lives in test_peer_identity_loopback.py / _tcp.py)."""

    def test_peer_identity_and_binding_survive_fresh_store_instance(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        restarted = fi.PeerIdentityStore(Path(self._peers_tmp.name))
        self.assertEqual(restarted.status_of(peer_id), fi.PEER_STATUS_ACTIVE)
        self.assertTrue(restarted.is_relationship_bound_to_peer(peer_id, relationship["relationship_id"]))

    def test_peer_revocation_survives_fresh_store_instance(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        self.peer_store.revoke_peer(peer_id)
        restarted = fi.PeerIdentityStore(Path(self._peers_tmp.name))
        self.assertEqual(restarted.status_of(peer_id), fi.PEER_STATUS_REVOKED)
        self.assertIsNone(restarted.resolve_active(peer_id))


class TestHistoricalLineageAvailableAfterRevocation(_PeerIdentityTestCase):
    """Matrix item 14 -- revocation means no new trusted execution, not
    erased history: the disposition recorded for a request that executed
    BEFORE revocation must remain readable afterward."""

    def test_disposition_recorded_before_revocation_remains_readable(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        result, _ = self._process(transport, signed, replay_guard=self.replay_guard)
        self.assertEqual(result.status, fi.CAP_COMPLETED)

        self.peer_store.revoke_peer(peer_id, reason="test: revoke after execution")

        disposition = self.replay_guard.get(signed.request_id)
        self.assertIsNotNone(disposition)
        self.assertEqual(disposition["source_peer_id"], peer_id)
        self.assertEqual(disposition["relationship_id"], relationship["relationship_id"])
        self.assertEqual(disposition["actor_id"], PHONE_ID)
        self.assertEqual(disposition["status"], fi.CAP_COMPLETED)


class TestPeerIdOnWireAsNonSecretMetadata(_PeerIdentityTestCase):
    """Matrix items 15 & 16."""

    def test_peer_id_present_on_wire_and_no_secret_material_present(self):
        from fabric.loopback import wire

        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        secret = self.key_store.resolve_key(relationship["key_id"])
        transport, signed = self._build_signed_request(relationship, peer_id)

        wire_dict = wire.capability_request_to_wire(signed)
        self.assertEqual(wire_dict["source_peer_id"], peer_id)  # present, non-secret

        wire_bytes = json.dumps(wire_dict).encode("utf-8")
        self.assertNotIn(secret, wire_bytes)
        self.assertNotIn(secret.hex().encode("ascii"), wire_bytes)

        # Peer store's own metadata/binding ledgers must also stay secret-free.
        peer_ledger_text = self.peer_store.ledger_path.read_text()
        self.assertNotIn(secret.hex(), peer_ledger_text)
        bindings_text = self.peer_store.bindings_path.read_text()
        self.assertNotIn(secret.hex(), bindings_text)


class TestActorIdRemainsIndependent(_PeerIdentityTestCase):
    """Matrix item 17 -- peer_id and actor_id are never automatically
    equated; a single peer_id can appear alongside different actor_id
    values without either governing the other."""

    def test_same_peer_id_with_different_actor_id_is_not_conflated(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        different_actor_authority = _authority((self.spy.capability_id,), actor="SOME-OTHER-ACTOR")
        transport, signed = self._build_signed_request(relationship, peer_id, cap_authority=different_actor_authority)
        result, _ = self._process(transport, signed)
        # Executes fine -- peer_id validity does not depend on, or get
        # checked against, actor_id at all.
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(signed.authority_context.actor_id, "SOME-OTHER-ACTOR")
        self.assertNotEqual(signed.authority_context.actor_id, peer_id)


class TestExistingBehaviorUnchangedWithoutPeerStore(_PeerIdentityTestCase):
    """Matrix item 18 -- omitting peer_store preserves every prior
    mission's proven behavior exactly."""

    def test_omitting_peer_store_falls_back_to_pairing_only_path(self):
        relationship = self._confirmed_relationship()
        transport, signed = self._build_signed_request(relationship, None)  # no source_peer_id at all
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, pairing_store=self.pairing_store,
        )  # no peer_store
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)

    def test_peer_store_without_pairing_store_fails_closed(self):
        relationship = self._confirmed_relationship()
        peer_id = self._peer_bound_to(relationship)
        transport, signed = self._build_signed_request(relationship, peer_id)
        result, _ = fi.process_remote_capability_request(
            signed, transport, key_store=self.key_store, peer_store=self.peer_store,
        )  # no pairing_store -- misconfiguration
        self.assertEqual(result.status, fi.CAP_FAILED)
        self.assertEqual(self.spy.invocation_count, 0)


if __name__ == "__main__":
    unittest.main()
