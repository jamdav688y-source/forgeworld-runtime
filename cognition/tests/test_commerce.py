"""C1 commercial evidence tests: schema, provenance, transitions, money
semantics (payment, refund, dispute, correction, reversal), separation of
hypotheses from outcomes, independent-buyer repeatability, privacy,
determinism and authority. Synthetic data only; temporary stores only."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition import commerce as cm
from cognition import cxp, exchange, lineage
from cognition.tests._commerce_events import OFFER, PILOT_PRICE, digest, payment_check, signal
from cognition.tests.test_exchange import snapshot

POLICY = cm.PaymentPolicy(policy_id="policy-payment-reconciliation-v1", approved_by="operator-synthetic")
PAY_REF = digest("synthetic-processor-txn-0001")


class CommerceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-c1-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.x = exchange.CognitiveExchange(self.tmp / "store")

    def accept(self, raw, x=None):
        receipt = (x or self.x).ingest(raw)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt.record_id

    def refused(self, raw, code):
        receipt = self.x.ingest(raw)
        self.assertEqual((receipt.status, receipt.error_code), (exchange.REJECTED, code), receipt.detail)

    def state(self, engagement="eng-pilot-a", policy=POLICY, x=None):
        return cm.engagement_state(x or self.x, engagement, policy)

    def verified_payment(self, engagement="eng-pilot-a", account="acct-buyer-a", ref=PAY_REF, amount=PILOT_PRICE, x=None):
        x = x or self.x
        claim = signal(cm.PAYMENT_CONFIRMED, engagement, account, amount=amount, payment_reference_digest=ref)
        claim_id = self.accept(claim, x)
        vr = self.accept(payment_check(x.get_record(claim_id).content_id), x)
        return self.accept(dict(claim, verification=cxp.VER_VERIFIED, verification_ref=vr), x)

    def pipeline(self, engagement="eng-pilot-a", account="acct-buyer-a", upto=cm.VALUE_MEASURED, x=None,
                 independence_key=None, ref=None):
        """A complete synthetic pilot, stopping after `upto`."""
        x = x or self.x
        ref = ref or digest(f"synthetic-processor-txn-{engagement}")
        steps = [
            (cm.OPPORTUNITY_IDENTIFIED, dict(summary="Intake handoffs lose about two days per order.")),
            (cm.PROBLEM_QUALIFIED, dict(summary="Owner confirms the delay costs repeat orders.")),
            (cm.INTEREST_CONFIRMED, dict(summary="Owner asked for a fixed-price proposal.")),
            (cm.PROPOSAL_SENT, dict(offer_ref=OFFER, amount=PILOT_PRICE, document_digest=digest(f"proposal-{engagement}"))),
            (cm.CONTRACT_SIGNED, dict(offer_ref=OFFER, amount=PILOT_PRICE, document_digest=digest(f"contract-{engagement}"))),
            (cm.INVOICE_ISSUED, dict(amount=PILOT_PRICE, document_digest=digest(f"invoice-{engagement}"))),
            (cm.PAYMENT_CONFIRMED, None),
            (cm.DELIVERY_MILESTONE, dict(summary="Workflow map and loss register delivered.")),
            (cm.CUSTOMER_ACCEPTANCE, dict(document_digest=digest(f"acceptance-{engagement}"))),
            (cm.VALUE_MEASURED, dict(amount={"minor": 1200000, "currency": "USD"}, reason="MEASURED_SAVINGS",
                                     document_digest=digest(f"measurement-{engagement}"))),
        ]
        ids = {}
        for stage, fields in steps:
            if stage == cm.PAYMENT_CONFIRMED:
                ids[stage] = self.verified_payment(engagement, account, ref, x=x)
            else:
                key = independence_key if stage == cm.CONTRACT_SIGNED else None
                ids[stage] = self.accept(signal(stage, engagement, account, independence_key=key, **fields), x)
            if stage == upto:
                break
        return ids


class TestSchema(CommerceTestCase):
    def test_malformed_payloads(self):
        base = signal(cm.PROPOSAL_SENT, offer_ref=OFFER, amount=PILOT_PRICE, document_digest=digest("p"))
        cases = {
            "unknown key": lambda p: p.update(extra=1),
            "missing key": lambda p: p.pop("summary"),
            "unknown stage": lambda p: p.update(stage="SALE_CLOSED"),
            "promotion is not a stage": lambda p: p.update(stage="REPEATABLE_COMMERCIAL_CAPABILITY"),
            "bad engagement": lambda p: p.update(engagement_ref="Engagement A"),
            "named buyer": lambda p: p.update(account_ref="Jane Smith"),
            "float amount": lambda p: p.update(amount={"minor": 5000.0, "currency": "USD"}),
            "dollars as float": lambda p: p.update(amount={"minor": 49.99, "currency": "USD"}),
            "negative amount": lambda p: p.update(amount={"minor": -1, "currency": "USD"}),
            "bool amount": lambda p: p.update(amount={"minor": True, "currency": "USD"}),
            "bad currency": lambda p: p.update(amount={"minor": 1, "currency": "usd"}),
            "raw document id": lambda p: p.update(document_digest="INV-2026-0042"),
            "required missing": lambda p: p.update(document_digest=None),
            "forbidden present": lambda p: p.update(payment_reference_digest=digest("x")),
            "reason not allowed": lambda p: p.update(reason="WON"),
            "bad offer ref": lambda p: p.update(offer_ref="workflow diagnostic"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                raw = copy.deepcopy(base)
                mutate(raw["payload"])
                self.refused(raw, cxp.E_MALFORMED)

    def test_raw_payment_references_have_nowhere_to_go(self):
        self.pipeline(upto=cm.CONTRACT_SIGNED)
        for raw_ref in ("ch_3NqXYZ12345", "4111111111111111", "GB33BUKB20201555555555"):
            with self.subTest(raw_ref):
                self.refused(signal(cm.PAYMENT_CONFIRMED, amount=PILOT_PRICE, payment_reference_digest=raw_ref), cxp.E_MALFORMED)

    def test_every_stage_has_rules_and_rejects_interpretations(self):
        self.assertEqual(set(cm.STAGES), set(cm.STAGE_RULES))
        for stage in cm.STAGES:
            rules = cm.STAGE_RULES[stage]
            for provenance in (cxp.UNVERIFIED_INTERPRETATION, cxp.DERIVED, cxp.AUTHORIZED_CONCLUSION):
                self.assertNotIn(provenance, rules.get("provenance", (cxp.HUMAN_ASSERTED,)), (stage, provenance))


class TestProvenance(CommerceTestCase):
    def test_model_or_lens_interpretations_cannot_record_commerce(self):
        for stage, fields in ((cm.OPPORTUNITY_IDENTIFIED, dict(summary="Lens thinks this is a lead.")),
                              (cm.ESTIMATE_RECORDED, dict(amount=PILOT_PRICE, reason="ESTIMATED_SAVINGS"))):
            for provenance in (cxp.UNVERIFIED_INTERPRETATION, cxp.DERIVED):
                with self.subTest(stage=stage, provenance=provenance):
                    rep = cxp.REP_HYPOTHESIS if stage == cm.ESTIMATE_RECORDED else cxp.REP_PARAPHRASE
                    self.refused(signal(stage, provenance=provenance, representation=rep, **fields), cxp.E_KIND_RULE)

    def test_buyer_money_and_acceptance_stages_require_a_human(self):
        self.pipeline(upto=cm.CONTRACT_SIGNED)
        for provenance in (cxp.OBSERVED, cxp.SYSTEM_ASSERTED, cxp.AUTHORIZED_CONCLUSION):
            with self.subTest(provenance):
                self.refused(signal(cm.PAYMENT_CONFIRMED, provenance=provenance, amount=PILOT_PRICE,
                                    payment_reference_digest=PAY_REF), cxp.E_KIND_RULE)
                self.refused(signal(cm.INTEREST_CONFIRMED, provenance=provenance, summary="Wants a proposal."),
                             cxp.E_KIND_RULE)

    def test_buyer_conversations_need_consent(self):
        self.refused(signal(cm.PROBLEM_QUALIFIED, consent_ref=None, summary="Owner confirms delay."),
                     cxp.E_PRIVACY_CONSENT_REQUIRED)

    def test_estimates_are_hypotheses_and_never_verified(self):
        self.refused(signal(cm.ESTIMATE_RECORDED, representation=cxp.REP_PARAPHRASE, amount=PILOT_PRICE,
                            reason="ESTIMATED_SAVINGS"), cxp.E_KIND_RULE)
        self.refused(signal(cm.ESTIMATE_RECORDED, representation=cxp.REP_HYPOTHESIS, amount=PILOT_PRICE,
                            reason="ESTIMATED_SAVINGS", verification=cxp.VER_VERIFIED,
                            verification_ref="cxp-rec-" + "0" * 64), cxp.E_KIND_RULE)


class TestPrivacy(CommerceTestCase):
    def test_sensitive_free_text_is_refused(self):
        for text in ("Contact the owner at owner@example.com", "Call +1 415 555 0134 tomorrow",
                     "Card 4111 1111 1111 1111 on file", "Their IBAN is in the notes", "routing details attached"):
            with self.subTest(text):
                self.refused(signal(cm.OPPORTUNITY_IDENTIFIED, summary=text), cxp.E_SENSITIVE_DATA)
        self.accept(signal(cm.OPPORTUNITY_IDENTIFIED, summary="Orders wait 2 days; noted on 2026-10-17."))

    def test_personal_records_are_not_persisted(self):
        self.refused(signal(cm.OPPORTUNITY_IDENTIFIED, summary="Owner frustration.", privacy=cxp.PRIV_PERSONAL,
                            consent_ref="consent-x"), cxp.E_PRIVACY_PERSISTENCE_UNSUPPORTED)

    def test_ledger_metadata_holds_no_amounts_or_text(self):
        self.pipeline()
        ledger = (self.tmp / "store" / "exchange.jsonl").read_text()
        self.assertNotIn("500000", ledger)
        self.assertNotIn("Owner confirms", ledger)
        self.assertIn("acct-buyer-a", ledger)  # pseudonyms and digests only

    def test_erasing_a_payment_removes_it_from_revenue(self):
        ids = self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        self.assertEqual(self.state()["revenue"]["net_retained"], {"USD": 500000})
        for rid in self.state()["milestones"][cm.PAYMENT_CONFIRMED]:
            self.x.erase(rid, "synthetic-erasure")
        self.assertEqual(self.state()["revenue"]["status"], cm.REVENUE_NONE)
        self.assertIn(ids[cm.PAYMENT_CONFIRMED], {m["record_id"] for m in self.x.all_record_metadata()})


class TestTransitions(CommerceTestCase):
    def test_out_of_order_stages_are_refused(self):
        self.accept(signal(cm.OPPORTUNITY_IDENTIFIED, summary="Lead."))
        refusals = [
            signal(cm.CONTRACT_SIGNED, offer_ref=OFFER, amount=PILOT_PRICE, document_digest=digest("c")),
            signal(cm.INVOICE_ISSUED, amount=PILOT_PRICE, document_digest=digest("i")),
            signal(cm.PAYMENT_CONFIRMED, amount=PILOT_PRICE, payment_reference_digest=PAY_REF),
            signal(cm.REFUND_ISSUED, amount=PILOT_PRICE, payment_reference_digest=PAY_REF),
            signal(cm.DELIVERY_MILESTONE, summary="Delivered."),
            signal(cm.CUSTOMER_ACCEPTANCE, document_digest=digest("a")),
            signal(cm.VALUE_MEASURED, amount=PILOT_PRICE, reason="MEASURED_SAVINGS", document_digest=digest("m")),
            signal(cm.RENEWAL, amount=PILOT_PRICE, document_digest=digest("r")),
            signal(cm.CHURNED, reason="CANCELLED"),
        ]
        for raw in refusals:
            with self.subTest(raw["payload"]["stage"]):
                self.refused(raw, cxp.E_TRANSITION_REFUSED)

    def test_acceptance_needs_delivery_not_just_a_demonstration(self):
        self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        self.accept(signal(cm.DEMONSTRATION_GIVEN, summary="Prototype shown in the readout."))
        self.refused(signal(cm.CUSTOMER_ACCEPTANCE, document_digest=digest("a")), cxp.E_TRANSITION_REFUSED)
        self.assertNotIn(cm.CUSTOMER_ACCEPTANCE, self.state()["milestones"])

    def test_targets_must_belong_to_the_engagement_and_fit_the_stage(self):
        ids = self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        other = self.accept(signal(cm.OPPORTUNITY_IDENTIFIED, engagement="eng-pilot-b", account="acct-buyer-b",
                                   summary="Another lead."))
        self.refused(signal(cm.CORRECTION, target_record=other, reason="ENTERED_IN_ERROR"), cxp.E_TRANSITION_REFUSED)
        self.refused(signal(cm.REVERSAL, target_record=ids[cm.PAYMENT_CONFIRMED], reason="CANCELLED"),
                     cxp.E_TRANSITION_REFUSED)  # money is reversed by REFUND/DISPUTE, not REVERSAL
        self.refused(signal(cm.DISPUTE_RESOLVED, target_record=ids[cm.CONTRACT_SIGNED], reason="WON"),
                     cxp.E_TRANSITION_REFUSED)
        self.refused(signal(cm.CORRECTION, target_record="cxp-rec-" + "e" * 64, reason="ENTERED_IN_ERROR"),
                     cxp.E_TRANSITION_REFUSED)

    def test_engagement_has_one_account_and_payment_refs_are_not_shared(self):
        self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        self.refused(signal(cm.DELIVERY_MILESTONE, account="acct-someone-else", summary="Delivered."),
                     cxp.E_TRANSITION_REFUSED)
        self.pipeline("eng-pilot-b", "acct-buyer-b", upto=cm.CONTRACT_SIGNED)
        self.refused(signal(cm.PAYMENT_CONFIRMED, "eng-pilot-b", "acct-buyer-b", amount=PILOT_PRICE,
                            payment_reference_digest=digest("synthetic-processor-txn-eng-pilot-a")),
                     cxp.E_TRANSITION_REFUSED)


class TestDistinctions(CommerceTestCase):
    def test_interest_is_not_approval_and_a_proposal_is_not_a_contract(self):
        self.pipeline(upto=cm.PROPOSAL_SENT)
        s = self.state()
        self.assertEqual(s["status"], cm.PROPOSAL_SENT)
        self.assertEqual(s["contracted"], {})
        self.assertEqual(s["hypotheses"]["proposed"], {"USD": 500000})
        self.assertEqual(s["revenue"]["status"], cm.REVENUE_NONE)

    def test_an_invoice_is_not_a_payment(self):
        self.pipeline(upto=cm.INVOICE_ISSUED)
        s = self.state()
        self.assertEqual((s["invoiced"], s["revenue"]["net_retained"], s["revenue"]["status"]),
                         ({"USD": 500000}, {}, cm.REVENUE_NONE))

    def test_estimates_never_become_revenue_or_measured_value(self):
        self.accept(signal(cm.ESTIMATE_RECORDED, representation=cxp.REP_HYPOTHESIS,
                           amount={"minor": 10 ** 9, "currency": "USD"}, reason="ESTIMATED_SAVINGS"))
        s = self.state()
        self.assertEqual(len(s["hypotheses"]["estimates"]), 1)
        self.assertEqual((s["measured_value"], s["revenue"]["net_retained"], s["status"]), ({}, {}, None))

    def test_full_pilot_separates_estimate_contract_payment_and_measurement(self):
        self.pipeline()
        s = self.state()
        self.assertEqual(s["status"], cm.VALUE_MEASURED)
        self.assertEqual(s["revenue"]["status"], cm.REVENUE_VERIFIED)
        self.assertEqual(s["revenue"]["net_retained"], {"USD": 500000})
        self.assertEqual(s["measured_value"], {"USD": 1200000})
        self.assertEqual(s["hypotheses"]["label"], "HYPOTHESES_AND_OFFERS_ARE_NOT_REVENUE")
        self.assertFalse(s["grants_execution_authority"])


class TestPaymentVerification(CommerceTestCase):
    def test_unverified_payment_is_a_claim_not_revenue(self):
        self.pipeline(upto=cm.CONTRACT_SIGNED)
        self.accept(signal(cm.PAYMENT_CONFIRMED, amount=PILOT_PRICE, payment_reference_digest=PAY_REF))
        s = self.state()
        self.assertEqual((s["revenue"]["status"], s["revenue"]["net_retained"]), (cm.REVENUE_UNVERIFIED_CLAIM, {}))

    def test_no_policy_means_nothing_is_paid(self):
        self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        s = self.state(policy=None)
        self.assertEqual(s["revenue"]["status"], cm.REVENUE_UNVERIFIED_CLAIM)
        self.assertEqual({r["reason"] for r in s["revenue"]["inadmissible_payment_records"]}, {"NO_POLICY"})

    def test_forged_or_inadmissible_verification_is_not_counted(self):
        self.pipeline(upto=cm.CONTRACT_SIGNED)
        claim = signal(cm.PAYMENT_CONFIRMED, amount=PILOT_PRICE, payment_reference_digest=PAY_REF)
        content_id = self.x.get_record(self.accept(claim)).content_id
        for method, provenance, reason in (("model-consensus", cxp.HUMAN_ASSERTED, "METHOD_NOT_ADMISSIBLE"),
                                           ("payment-reconciliation", cxp.AUTHORIZED_CONCLUSION, "PROVENANCE_NOT_ADMISSIBLE")):
            vr = self.accept(payment_check(content_id, method=method, provenance=provenance))
            self.accept(dict(claim, verification=cxp.VER_VERIFIED, verification_ref=vr,
                             sources=[{"source_type": "human_statement", "locator": f"forged-{method}-{provenance}"}]))
        s = self.state()
        self.assertEqual(s["revenue"]["status"], cm.REVENUE_UNVERIFIED_CLAIM)
        self.assertEqual(sorted(r["reason"] for r in s["revenue"]["inadmissible_payment_records"]),
                         ["METHOD_NOT_ADMISSIBLE", "PROVENANCE_NOT_ADMISSIBLE"])
        # a VERIFIED claim needs a real matching VERIFICATION_RESULT at all
        self.refused(dict(claim, verification=cxp.VER_VERIFIED, verification_ref="cxp-rec-" + "1" * 64),
                     cxp.E_VERIFICATION_UNSUPPORTED)

    def test_conflicting_amounts_for_one_payment_reference_count_nothing(self):
        self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        self.accept(signal(cm.PAYMENT_CONFIRMED, entry="inflated", amount={"minor": 5000000, "currency": "USD"},
                           payment_reference_digest=digest("synthetic-processor-txn-eng-pilot-a")))
        s = self.state()
        self.assertEqual(s["revenue"]["net_retained"], {})
        self.assertIn("PAYMENT_CONFLICT", s["flags"])

    def test_duplicate_payment_entries_count_once(self):
        self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        dup = signal(cm.PAYMENT_CONFIRMED, entry="entered-twice", amount=PILOT_PRICE,
                     payment_reference_digest=digest("synthetic-processor-txn-eng-pilot-a"))
        self.accept(dup)
        self.assertEqual(self.x.ingest(dup).status, exchange.DUPLICATE_OCCURRENCE)
        self.assertEqual(self.state()["revenue"]["net_retained"], {"USD": 500000})


class TestRefundsDisputesCorrectionsReversals(CommerceTestCase):
    REF = digest("synthetic-processor-txn-eng-pilot-a")

    def test_partial_and_full_refunds_reduce_net_but_keep_history(self):
        ids = self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        self.accept(signal(cm.REFUND_ISSUED, entry="r1", amount={"minor": 100000, "currency": "USD"},
                           payment_reference_digest=self.REF))
        s = self.state()
        self.assertEqual((s["revenue"]["verified_gross"], s["revenue"]["refunded"], s["revenue"]["net_retained"]),
                         ({"USD": 500000}, {"USD": 100000}, {"USD": 400000}))
        self.accept(signal(cm.REFUND_ISSUED, entry="r2", amount={"minor": 900000, "currency": "USD"},
                           payment_reference_digest=self.REF))
        s = self.state()
        self.assertEqual((s["revenue"]["status"], s["revenue"]["net_retained"]), (cm.REVENUE_FULLY_REVERSED, {"USD": 0}))
        self.assertEqual(s["revenue"]["anomalies"][0]["issue"], "EXCEEDS_REMAINING_PAYMENT")
        self.assertIsNotNone(self.x.get_record(ids[cm.PAYMENT_CONFIRMED]))

    def test_disputes_hold_then_deduct_or_release(self):
        self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        dispute = self.accept(signal(cm.DISPUTE_OPENED, amount=PILOT_PRICE, payment_reference_digest=self.REF))
        s = self.state()
        self.assertEqual((s["revenue"]["status"], s["revenue"]["held_in_open_dispute"]),
                         (cm.REVENUE_HELD_IN_DISPUTE, {"USD": 500000}))
        self.assertIn("DISPUTE_OPEN", s["flags"])
        won = self.accept(signal(cm.DISPUTE_RESOLVED, entry="won", target_record=dispute, reason="WON"))
        self.assertEqual(self.state()["revenue"]["net_retained"], {"USD": 500000})
        self.accept(signal(cm.CORRECTION, entry="fix", target_record=won, reason="ENTERED_IN_ERROR"))
        self.accept(signal(cm.DISPUTE_RESOLVED, entry="lost", target_record=dispute, reason="LOST"))
        s = self.state()
        self.assertEqual((s["revenue"]["dispute_lost"], s["revenue"]["status"]), ({"USD": 500000}, cm.REVENUE_FULLY_REVERSED))

    def test_correction_voids_and_a_correction_of_a_correction_restores(self):
        ids = self.pipeline(upto=cm.PAYMENT_CONFIRMED)
        fix = self.accept(signal(cm.CORRECTION, target_record=ids[cm.CONTRACT_SIGNED], reason="ENTERED_IN_ERROR"))
        s = self.state()
        self.assertIn(ids[cm.CONTRACT_SIGNED], s["voided"])
        self.assertEqual(s["contracted"], {})
        self.assertEqual(s["revenue"]["net_retained"], {})  # payment's prerequisite is gone: it stops counting
        self.assertIn(ids[cm.INVOICE_ISSUED], s["prerequisite_broken"])
        self.accept(signal(cm.CORRECTION, entry="undo", target_record=fix, reason="ENTERED_IN_ERROR"))
        s = self.state()
        self.assertEqual((s["contracted"], s["revenue"]["net_retained"]), ({"USD": 500000}, {"USD": 500000}))

    def test_reversal_undoes_a_milestone_without_deleting_it(self):
        ids = self.pipeline(upto=cm.CUSTOMER_ACCEPTANCE)
        self.accept(signal(cm.REVERSAL, target_record=ids[cm.CUSTOMER_ACCEPTANCE], reason="WITHDRAWN"))
        s = self.state()
        self.assertNotIn(cm.CUSTOMER_ACCEPTANCE, s["milestones"])
        self.assertEqual(s["status"], cm.DELIVERY_MILESTONE)
        self.assertIn(ids[cm.CUSTOMER_ACCEPTANCE], s["reversed"])
        self.assertIsNotNone(self.x.get_record(ids[cm.CUSTOMER_ACCEPTANCE]))
        self.refused(signal(cm.VALUE_MEASURED, amount=PILOT_PRICE, reason="MEASURED_SAVINGS",
                            document_digest=digest("m")), cxp.E_TRANSITION_REFUSED)
        self.refused(signal(cm.REVERSAL, entry="again", target_record=ids[cm.CUSTOMER_ACCEPTANCE], reason="WITHDRAWN"),
                     cxp.E_TRANSITION_REFUSED)


class TestRepeatability(CommerceTestCase):
    def test_one_sale_is_not_repeatable(self):
        self.pipeline()
        r = cm.repeatability(self.x, OFFER, POLICY)
        self.assertEqual((r["status"], r["independent_buyers"]), (cm.REPEATABILITY_INSUFFICIENT, 1))

    def test_three_independent_buyers_make_a_candidate_never_a_promotion(self):
        for tag in ("a", "b", "c"):
            self.pipeline(f"eng-pilot-{tag}", f"acct-buyer-{tag}")
        r = cm.repeatability(self.x, OFFER, POLICY)
        self.assertEqual((r["status"], r["independent_buyers"]), (cm.REPEATABILITY_CANDIDATE, 3))
        self.assertTrue(r["promotion_requires_human_decision"])
        self.assertFalse(r["grants_execution_authority"])
        self.assertEqual(cm.repeatability(self.x, OFFER, None)["status"], cm.REPEATABILITY_INSUFFICIENT)

    def test_repeat_purchases_or_shared_origins_are_one_buyer(self):
        self.pipeline("eng-pilot-a", "acct-buyer-a")
        self.pipeline("eng-pilot-a2", "acct-buyer-a")  # same buyer again
        self.pipeline("eng-pilot-b", "acct-buyer-b", independence_key="introducer-network-x")
        self.pipeline("eng-pilot-c", "acct-buyer-c", independence_key="introducer-network-x")
        r = cm.repeatability(self.x, OFFER, POLICY)
        self.assertEqual(r["independent_buyers"], 2)
        self.assertEqual(r["buyer_groups"], [["eng-pilot-a", "eng-pilot-a2"], ["eng-pilot-b", "eng-pilot-c"]])

    def test_unaccepted_or_unmeasured_sales_do_not_qualify(self):
        self.pipeline("eng-pilot-a", "acct-buyer-a")
        self.pipeline("eng-pilot-b", "acct-buyer-b", upto=cm.PAYMENT_CONFIRMED)
        self.pipeline("eng-pilot-c", "acct-buyer-c", upto=cm.CUSTOMER_ACCEPTANCE)
        r = cm.repeatability(self.x, OFFER, POLICY)
        self.assertEqual(r["qualifying_engagements"], ["eng-pilot-a"])
        missing = {e["engagement_ref"]: e["missing"] for e in r["non_qualifying_engagements"]}
        self.assertEqual(missing, {"eng-pilot-b": ["customer_acceptance", "measured_value"],
                                   "eng-pilot-c": ["measured_value"]})


class TestDeterminismAndAuthority(CommerceTestCase):
    def test_replay_and_independent_stores_agree(self):
        events, real_ingest = [], self.x.ingest
        self.x.ingest = lambda raw: (events.append(copy.deepcopy(raw)), real_ingest(raw))[1]
        self.pipeline()
        self.x.ingest = real_ingest
        before = snapshot(self.tmp / "store")
        first = self.state()
        for raw in events:  # exact replay of every event
            self.assertEqual(self.x.ingest(raw).status, exchange.DUPLICATE_OCCURRENCE)
        self.assertEqual(snapshot(self.tmp / "store"), before)
        self.assertEqual(self.state(), first)
        other = exchange.CognitiveExchange(self.tmp / "other")
        self.pipeline(x=other)
        self.assertEqual(self.state(x=other), first)
        self.assertEqual(snapshot(self.tmp / "other"), before)

    def test_queries_are_read_only_and_grant_nothing(self):
        self.pipeline()
        before = snapshot(self.tmp / "store")
        self.state()
        cm.repeatability(self.x, OFFER, POLICY)
        self.assertEqual(snapshot(self.tmp / "store"), before)
        self.assertFalse(POLICY.grants_execution_authority)
        for name in dir(cm):
            for word in ("promote", "execute", "authorize", "publish", "contact", "charge", "send"):
                self.assertNotIn(word, name.lower())

    def test_commercial_records_trace_to_their_sources(self):
        ids = self.pipeline(upto=cm.CONTRACT_SIGNED)
        t = lineage.trace(self.x.record_metadata, ids[cm.CONTRACT_SIGNED])
        self.assertEqual(t["epistemic_class"], lineage.DIRECT_OBSERVATION)
        self.assertEqual(t["sources"][0]["locator"], "operator-log:eng-pilot-a:contract_signed")

    def test_policy_validation(self):
        with self.assertRaises(ValueError):
            cm.PaymentPolicy("p1", "operator", admissible_provenance=(cxp.UNVERIFIED_INTERPRETATION,))
        with self.assertRaises(ValueError):
            cm.PaymentPolicy("p1", "operator", admissible_methods=())
        with self.assertRaises(cxp.CXPError):
            cm.PaymentPolicy("../p", "operator")


if __name__ == "__main__":
    unittest.main()
