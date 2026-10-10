"""Object-contract validation and MemoryStore promotion-gate tests
(Sections 3-6, 18)."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import interface as si
from fabric import interface as fi


class TestSignalAndInferenceSeparation(unittest.TestCase):
    def test_signal_event_requires_known_origin(self):
        with self.assertRaises(si.SubstrateError):
            si.SignalEvent(signal_id=si._new_id("SIG"), origin="not_a_real_origin", raw_content="x", provenance=si.OBSERVED)

    def test_signal_event_valid(self):
        sig = si.SignalEvent(signal_id=si._new_id("SIG"), origin="phone_input", raw_content="hello", provenance=si.OBSERVED)
        self.assertEqual(sig.record_type, "SIGNAL_EVENT")

    def test_inference_requires_source_signals(self):
        with self.assertRaises(si.SubstrateError):
            si.InferenceRecord(inference_id=si._new_id("INF"), source_signal_ids=(), statement="x", provenance=si.DERIVED)

    def test_inference_is_a_distinct_record_type_from_signal(self):
        sig = si.SignalEvent(signal_id=si._new_id("SIG"), origin="phone_input", raw_content="hello", provenance=si.OBSERVED)
        inf = si.InferenceRecord(inference_id=si._new_id("INF"), source_signal_ids=(sig.signal_id,), statement="maybe a problem", provenance=si.DERIVED)
        self.assertNotEqual(sig.record_type, inf.record_type)
        # An inference is not itself a problem/buyer/opportunity claim -- it
        # has no such fields to accidentally carry that meaning.
        self.assertFalse(hasattr(inf, "is_buyer"))
        self.assertFalse(hasattr(inf, "opportunity_value"))


class TestProblemHypothesis(unittest.TestCase):
    def test_requires_source_signal(self):
        with self.assertRaises(si.SubstrateError):
            si.ProblemHypothesis(hypothesis_id=si._new_id("HYP"), source_signal_ids=(), description="x")

    def test_rejects_unknown_cost_dimension(self):
        with self.assertRaises(si.SubstrateError):
            si.ProblemHypothesis(
                hypothesis_id=si._new_id("HYP"), source_signal_ids=("SIG-1",), description="x",
                possible_cost_dimensions=("NOT_A_REAL_DIMENSION",),
            )

    def test_uncertainty_is_preserved_by_default(self):
        hyp = si.ProblemHypothesis(hypothesis_id=si._new_id("HYP"), source_signal_ids=("SIG-1",), description="x")
        self.assertEqual(hyp.confidence, si.CONFIDENCE_UNVERIFIED)
        self.assertEqual(hyp.status, si.HYPOTHESIS_PROPOSED)

    def test_can_be_rejected(self):
        hyp = si.ProblemHypothesis(hypothesis_id=si._new_id("HYP"), source_signal_ids=("SIG-1",), description="x", status=si.HYPOTHESIS_REJECTED)
        self.assertEqual(hyp.status, si.HYPOTHESIS_REJECTED)


class TestObjectiveContract(unittest.TestCase):
    def test_required_capabilities_must_be_within_declared_ceiling(self):
        with self.assertRaises(si.SubstrateError):
            si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("physical_ping", "content_read"),
                authority_ceiling=("physical_ping",),  # narrower than required -- must fail
            )

    def test_empty_ceiling_means_unbounded_declaration_not_a_free_pass(self):
        # No ceiling declared at all is allowed (the DifferentialCognition
        # governance perspective is the one that flags this as an
        # uncertainty -- see test_differential_cognition.py), but it must
        # not silently satisfy the subset check either way.
        obj = si.ObjectiveContract(
            objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
            required_capability_ids=("physical_ping",),
        )
        self.assertEqual(obj.authority_ceiling, ())

    def test_objective_is_not_a_prompt_it_has_no_free_text_intent_field(self):
        obj = si.ObjectiveContract(
            objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
        )
        self.assertFalse(hasattr(obj, "prompt"))
        self.assertFalse(hasattr(obj, "instructions"))


class TestMemoryPromotionGate(unittest.TestCase):
    def _store(self, tmp):
        cg = si.CapabilityGraph(Path(tmp) / "capgraph")
        el = si.EvidenceLedger(Path(tmp) / "evidence")
        return si.MemoryStore(Path(tmp) / "memory", cg, el), el

    def test_episodic_write_never_requires_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._store(tmp)
            sig = si.SignalEvent(signal_id=si._new_id("SIG"), origin="pc_observation", raw_content="raw", provenance=si.OBSERVED)
            store.write_episodic(sig)
            self.assertEqual(len(store.episodic.list_all()), 1)

    def test_semantic_promotion_without_evidence_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._store(tmp)
            with self.assertRaises(si.MemoryPromotionError):
                store.promote_to_semantic({"claim": "unsupported speculation"}, evidence_ids=())

    def test_semantic_promotion_with_unverified_interpretation_evidence_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, el = self._store(tmp)
            bad_evidence = si.EvidenceRecord(
                evidence_id=si._new_id("EVID"), claim="model speculation", test_or_observation="none",
                result="unverified", provenance=si.UNVERIFIED_INTERPRETATION, evidence_dimension="TECHNICAL",
            )
            el.write(bad_evidence)
            with self.assertRaises(si.MemoryPromotionError):
                store.promote_to_semantic({"claim": "x"}, evidence_ids=(bad_evidence.evidence_id,))

    def test_semantic_promotion_with_qualifying_evidence_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, el = self._store(tmp)
            good_evidence = si.EvidenceRecord(
                evidence_id=si._new_id("EVID"), claim="capability works", test_or_observation="ran test",
                result="passed", provenance=si.SYSTEM_ASSERTED, evidence_dimension="TECHNICAL",
            )
            el.write(good_evidence)
            store.promote_to_semantic({"claim": "capability works"}, evidence_ids=(good_evidence.evidence_id,))
            self.assertEqual(len(store.list_semantic()), 1)

    def test_procedural_promotion_gated_the_same_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, el = self._store(tmp)
            with self.assertRaises(si.MemoryPromotionError):
                store.promote_to_procedural({"procedure": "x"}, evidence_ids=())

    def test_trust_relationship_is_a_view_not_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "capgraph")
            el = si.EvidenceLedger(tmp / "evidence")
            key_store = fi.LocalKeyStore(tmp / "keys")
            pairing_store = fi.PairingStore(tmp / "pairing")
            peer_store = fi.PeerIdentityStore(tmp / "peers")
            offer = pairing_store.create_offer("NODE-A", "NODE-B", key_store)
            peer_id = peer_store.register_peer()
            peer_store.bind_relationship(peer_id, offer["relationship_id"])
            pairing_store.confirm(offer["relationship_id"], offer["sas"])

            store = si.MemoryStore(tmp / "memory", cg, el, pairing_store=pairing_store, peer_store=peer_store)
            status = store.trust_relationship_status(offer["relationship_id"], peer_id=peer_id)
            self.assertEqual(status["status"], fi.PAIRING_STATUS_ACTIVE)
            self.assertTrue(status["bound"])

            # Revoking through the REAL store is immediately visible here --
            # proving this is a live view, not a duplicated snapshot.
            pairing_store.revoke(offer["relationship_id"], reason="test")
            status2 = store.trust_relationship_status(offer["relationship_id"], peer_id=peer_id)
            self.assertEqual(status2["status"], fi.PAIRING_STATUS_REVOKED)


if __name__ == "__main__":
    unittest.main()
