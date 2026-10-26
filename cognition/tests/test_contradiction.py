"""R2 Contradiction Memory tests, including the nine-step acceptance
demonstration. Synthetic data grounded in the real Phase 0 change: before
it, a requester's own AuthorityContext authorized execution; after it, only
a receiver-held grant does."""
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition.tests import _events as ev
from cognition.tests.test_exchange import snapshot
from cognition import contradiction as cm
from cognition import cxp, exchange, lineage, synthetic

PRE_PHASE0_DOC = "synthetic://forgeworld/pre-phase-0-design-note"
POLICY = cm.ResolutionPolicy(policy_id="policy-operator-review-v1", approved_by="operator-synthetic",
                             admissible_provenance=(cxp.HUMAN_ASSERTED,), admissible_methods=("operator-review",))


class ContradictionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-r2-contradiction-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.x = exchange.CognitiveExchange(self.tmp / "store",
                                            consumers=(synthetic.SourceAuditConsumer(), synthetic.GovernanceTermConsumer()))

    def accept(self, raw):
        receipt = self.x.ingest(raw)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt.record_id

    def content_id(self, record_id):
        return self.x.get_record(record_id).content_id

    def two_claims(self):
        obs_a = self.accept(ev.observation(statement=synthetic.PHASE0_SUBJECT))
        obs_b = self.accept(ev.observation(statement="Execution is authorized by the requester's AuthorityContext.",
                                           sources=[ev.source(PRE_PHASE0_DOC, source_type="document")]))
        claim_a = self.accept(ev.claim([obs_a], statement="Only a receiver-held grant can authorize execution."))
        claim_b = self.accept(ev.claim([obs_b], statement="A requester-signed AuthorityContext is sufficient to execute."))
        return obs_a, obs_b, claim_a, claim_b


class TestR2Demonstration(ContradictionTestCase):
    def test_nine_step_acceptance(self):
        # 1-2: two conflicting claims enter CXP, each keeping its own lineage
        obs_a, obs_b, claim_a, claim_b = self.two_claims()
        self.assertEqual(lineage.trace(self.x.record_metadata, claim_a)["observation_roots"], [obs_a])
        self.assertEqual(lineage.trace(self.x.record_metadata, claim_b)["observation_roots"], [obs_b])

        # 3: a contradiction record is created
        raw = ev.contradiction([claim_a, claim_b], summary="Receiver-held vs requester-held authority.",
                               conditions=["an operator-reviewed run of fabric/tests/test_receiver_authorization.py"])
        contradiction_id = self.accept(raw)
        self.assertEqual(cm.contradictions_for(self.x, claim_a), (contradiction_id,))

        # 4: repeated derivatives do not become independent evidence
        echoes = [self.accept(ev.claim([claim_b], statement=f"echo {i}", representation=cxp.REP_PARAPHRASE))
                  for i in range(5)]
        self.assertEqual(lineage.shared_origins(self.x.record_metadata, echoes)["independent_origin_count"], 1)
        self.assertEqual(self.x.ingest(ev.claim(echoes, evidence=cxp.EV_INDEPENDENT_SOURCES)).error_code,
                         cxp.E_EVIDENCE_INFLATION)

        # 5: lineage reconstructs the original sources of the contradiction
        t = lineage.trace(self.x.record_metadata, contradiction_id)
        self.assertEqual(t["observation_roots"], sorted([obs_a, obs_b]))
        self.assertEqual(sorted(s["locator"] for s in t["sources"]), sorted([synthetic.PHASE0_COMMIT, PRE_PHASE0_DOC]))
        self.assertEqual(t["epistemic_class"], lineage.INFERRED)

        # 6: unresolved without admissible verification -- however lopsided the repetition
        state = cm.assess(self.x, contradiction_id, POLICY)
        self.assertEqual(state["status"], cm.OPEN)
        b_row = next(c for c in state["claims"] if c["claim_id"] == claim_b)
        self.assertEqual(b_row["non_admissible_signals"]["restatement_count"], 5)
        self.assertEqual(state["resolution_conditions"],
                         ["an operator-reviewed run of fabric/tests/test_receiver_authorization.py"])

        # 7: a valid verification result supports a governed resolution
        vr = self.accept(ev.verification_result(self.content_id(claim_a)))
        self.assertEqual(cm.assess(self.x, contradiction_id)["status"], cm.OPEN)  # no policy, no resolution
        state = cm.assess(self.x, contradiction_id, POLICY)
        self.assertEqual((state["status"], state["resolved_in_favor_of"]), (cm.RESOLVED, claim_a))
        self.assertEqual(state["resolution_basis"], {"verification_results": [vr],
                                                     "policy_id": "policy-operator-review-v1",
                                                     "policy_approved_by": "operator-synthetic"})
        self.assertEqual(self.x.get_record(claim_b).verification, cxp.VER_UNVERIFIED)  # nothing rewritten

        # 8: replay creates no duplicate contradiction record
        before = snapshot(self.tmp / "store")
        self.assertEqual(self.x.ingest(raw).status, exchange.DUPLICATE_OCCURRENCE)
        reworded = self.x.ingest(ev.contradiction([claim_b, claim_a], summary="Same disagreement, new words."))
        self.assertEqual(reworded.error_code, cxp.E_DUPLICATE_CONTRADICTION)
        self.assertEqual(snapshot(self.tmp / "store"), before)
        self.assertEqual(len([m for m in self.x.all_record_metadata() if m["kind"] == cxp.KIND_CONTRADICTION]), 1)

        # 9: no execution authority is created or modified
        self.assertFalse(state["grants_execution_authority"])
        self.assertFalse(POLICY.grants_execution_authority)
        written = {p.relative_to(self.tmp).parts[0] for p in self.tmp.rglob("*")}
        self.assertEqual(written, {"store"})


class TestNoAutomaticResolution(ContradictionTestCase):
    def test_majority_repetition_and_model_agreement_do_not_resolve(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        for i in range(3):  # independent-looking support for B
            obs = self.accept(ev.observation(statement=f"B again {i}", sources=[ev.source(f"doc-{i}")]))
            self.accept(ev.claim([obs], statement="A requester-signed AuthorityContext is sufficient to execute.",
                                 provenance=cxp.UNVERIFIED_INTERPRETATION))  # "model agreement"
        for i in range(4):
            self.accept(ev.claim([claim_b], statement=f"restating B {i}"))
        self.assertEqual(cm.assess(self.x, cid, POLICY)["status"], cm.OPEN)

    def test_refuting_every_other_claim_does_not_verify_the_remaining_one(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        self.accept(ev.verification_result(self.content_id(claim_b), outcome=cxp.VER_REFUTED))
        state = cm.assess(self.x, cid, POLICY)
        self.assertEqual(state["status"], cm.OPEN)
        b_row = next(c for c in state["claims"] if c["claim_id"] == claim_b)
        self.assertEqual(len(b_row["opposing_evidence"]["verification_results"]), 1)

    def test_inadmissible_verification_is_reported_and_ignored(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        self.accept(ev.verification_result(self.content_id(claim_a), provenance=cxp.AUTHORIZED_CONCLUSION))
        wrong_method = ev.verification_result(self.content_id(claim_a))
        wrong_method["payload"]["method"] = "model-consensus"
        self.accept(wrong_method)
        state = cm.assess(self.x, cid, POLICY)
        self.assertEqual(state["status"], cm.OPEN)
        a_row = next(c for c in state["claims"] if c["claim_id"] == claim_a)
        reasons = sorted(r["reason"] for r in a_row["non_admissible_signals"]["inadmissible_verification_results"])
        self.assertEqual(reasons, [cm.NOT_ADMISSIBLE_METHOD, cm.NOT_ADMISSIBLE_PROVENANCE])
        no_policy = cm.assess(self.x, cid)
        self.assertEqual({r["reason"] for c in no_policy["claims"]
                          for r in c["non_admissible_signals"]["inadmissible_verification_results"]},
                         {cm.NOT_ADMISSIBLE_NO_POLICY})

    def test_conflicting_admissible_verification_escalates(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        self.accept(ev.verification_result(self.content_id(claim_a)))
        self.accept(ev.verification_result(self.content_id(claim_b)))
        self.assertEqual(cm.assess(self.x, cid, POLICY)["status"], cm.CONFLICTING_VERIFICATION)

    def test_verified_and_refuted_same_claim_escalates(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        self.accept(ev.verification_result(self.content_id(claim_a)))
        refute = ev.verification_result(self.content_id(claim_a), outcome=cxp.VER_REFUTED)
        refute["occurrence"]["emitter_id"] = "synthetic-operator-2"
        self.accept(refute)
        self.assertEqual(cm.assess(self.x, cid, POLICY)["status"], cm.CONFLICTING_VERIFICATION)

    def test_erasing_the_verification_reopens(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        vr = self.accept(ev.verification_result(self.content_id(claim_a)))
        self.assertEqual(cm.assess(self.x, cid, POLICY)["status"], cm.RESOLVED)
        self.x.erase(vr, "synthetic-erasure")
        self.assertEqual(cm.assess(self.x, cid, POLICY)["status"], cm.OPEN)

    def test_erased_claim_voids_the_contradiction(self):
        _, _, claim_a, claim_b = self.two_claims()
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        self.x.erase(claim_b, "synthetic-erasure")
        state = cm.assess(self.x, cid, POLICY)
        self.assertEqual(state["status"], cm.VOID)


class TestContradictionRecordRules(ContradictionTestCase):
    def test_structural_rules(self):
        _, _, claim_a, claim_b = self.two_claims()
        unsorted = ev.contradiction([claim_a, claim_b])
        unsorted["payload"]["claims"] = sorted([claim_a, claim_b], reverse=True)
        unsorted["derived_from"] = unsorted["payload"]["claims"]
        mismatched = ev.contradiction([claim_a, claim_b])
        mismatched["derived_from"] = [claim_a]
        no_conditions = ev.contradiction([claim_a, claim_b])
        no_conditions["payload"]["resolution_conditions"] = []
        cases = {
            "single claim": (ev.contradiction([claim_a]), cxp.E_MALFORMED),
            "unsorted claims": (unsorted, cxp.E_MALFORMED),
            "derived_from mismatch": (mismatched, cxp.E_KIND_RULE),
            "no resolution conditions": (no_conditions, cxp.E_MALFORMED),
            "declares itself verified": (ev.contradiction([claim_a, claim_b], verification=cxp.VER_CONTESTED), cxp.E_KIND_RULE),
            "not an inference": (ev.contradiction([claim_a, claim_b], representation=cxp.REP_QUOTATION), cxp.E_KIND_RULE),
            "unknown claim": (ev.contradiction([claim_a, "cxp-rec-" + "f" * 64]), cxp.E_LINEAGE_UNRESOLVED),
            "evidence inflation": (ev.contradiction([claim_a, claim_b], evidence=cxp.EV_INDEPENDENT_SOURCES),
                                   cxp.E_EVIDENCE_INFLATION),
            "authority smuggling": (ev.contradiction([claim_a, claim_b], payload={
                "claims": sorted([claim_a, claim_b]), "summary": "s", "resolution_conditions": ["c"],
                "grant": "content_read"}), cxp.E_AUTHORITY_FIELD_FORBIDDEN),
        }
        for name, (raw, code) in cases.items():
            with self.subTest(name):
                receipt = self.x.ingest(raw)
                self.assertEqual((receipt.status, receipt.error_code), (exchange.REJECTED, code), receipt.detail)

    def test_a_new_contradiction_is_allowed_once_the_old_one_is_erased(self):
        _, _, claim_a, claim_b = self.two_claims()
        old = self.accept(ev.contradiction([claim_a, claim_b]))
        self.x.erase(old, "synthetic-erasure")
        self.accept(ev.contradiction([claim_a, claim_b], summary="restated after erasure"))

    def test_assess_rejects_non_contradictions_and_is_read_only(self):
        _, _, claim_a, claim_b = self.two_claims()
        with self.assertRaises(cm.ContradictionError):
            cm.assess(self.x, claim_a)
        cid = self.accept(ev.contradiction([claim_a, claim_b]))
        before = snapshot(self.tmp / "store")
        first = cm.assess(self.x, cid, POLICY)
        self.assertEqual(cm.assess(self.x, cid, POLICY), first)
        self.assertEqual(snapshot(self.tmp / "store"), before)


class TestResolutionPolicy(unittest.TestCase):
    def test_policy_validation(self):
        good = dict(policy_id="p1", approved_by="operator", admissible_provenance=(cxp.HUMAN_ASSERTED,),
                    admissible_methods=("operator-review",))
        cm.ResolutionPolicy(**good)
        for field, bad in (("admissible_provenance", ()), ("admissible_provenance", (cxp.DERIVED,)),
                           ("admissible_methods", ()), ("admissible_methods", ("",))):
            with self.subTest(field=field, bad=bad), self.assertRaises(cm.ContradictionError):
                cm.ResolutionPolicy(**{**good, field: bad})
        for field in ("policy_id", "approved_by"):
            with self.subTest(field=field), self.assertRaises(cxp.CXPError):
                cm.ResolutionPolicy(**{**good, field: "../x"})


if __name__ == "__main__":
    unittest.main()
