from perception.src import claims, corroboration, entities, ingest, ocr, promotion, proposal, retrieval, schema
from perception.tests.base import PerceptionTestCase, fixture_path


class TestProposalPromotionVault(PerceptionTestCase):
    def setUp(self):
        super().setUp()
        self.obs = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        image_bytes = fixture_path("screenshot_1554.png").read_bytes()
        ocr_provider = ocr.FixtureOCRProvider({
            self.obs["source_image_sha256"]: {"text": "GitHub\nPocket Cortex\nInstagram", "confidence": 0.9}
        })
        ocr_signal = ocr.extract_ocr_signal(self.obs, image_bytes, ocr_provider)
        entity_signals = entities.extract_entities(self.obs, ocr_signal)
        by_text = {s["value"]["text"]: s for s in entity_signals if s["value"]["entity_type"] == "platform_name"}

        retrieval_provider = retrieval.FixtureRetrievalProvider({
            "GitHub": [
                {"url": "https://github.com/a", "title": "a", "snippet": "agrees", "confidence": 0.8},
                {"url": "https://wikipedia.org/b", "title": "b", "snippet": "agrees too", "confidence": 0.7},
            ],
            "Pocket Cortex": [
                {"url": "https://example.com/a", "title": "a", "snippet": "this is false and debunked", "confidence": 0.6},
                {"url": "https://another.com/b", "title": "b", "snippet": "confirmed real", "confidence": 0.6},
            ],
            "Instagram": [
                {"url": "https://mirror1.example.com/x", "title": "x", "snippet": "lone source", "confidence": 0.4},
            ],
        })
        candidates = (
            retrieval.retrieve_candidates(self.obs, [by_text["GitHub"]], retrieval_provider)
            + retrieval.retrieve_candidates(self.obs, [by_text["Pocket Cortex"]], retrieval_provider)
            + retrieval.retrieve_candidates(self.obs, [by_text["Instagram"]], retrieval_provider)
        )
        self.candidates_by_id = {c["id"]: c for c in candidates}

        result = corroboration.assess_corroboration(self.obs, candidates)
        self.rels_by_type = {r["relationship_type"]: r for r in result["relationships"]}

        def entity_for(rel):
            cand = next(c for c in candidates if c["id"] in rel["evidence_references"])
            return by_text[[k for k, v in by_text.items() if v["id"] == cand["evidence_references"][0]][0]]

        self.claim_corroborated = claims.extract_claim(self.obs, entity_for(self.rels_by_type["corroborates"]), self.rels_by_type["corroborates"])
        self.claim_contradicted = claims.extract_claim(self.obs, entity_for(self.rels_by_type["contradicts"]), self.rels_by_type["contradicts"])
        self.claim_unrelated = claims.extract_claim(self.obs, entity_for(self.rels_by_type["unrelated"]), self.rels_by_type["unrelated"])

    def test_corroborated_claim_promotes(self):
        prop = proposal.propose_capability(self.obs, self.claim_corroborated, self.rels_by_type["corroborates"], self.candidates_by_id)
        self.assertEqual(prop["validation_status"], schema.PROPOSED)

        claims_by_id = {self.claim_corroborated["id"]: self.claim_corroborated}
        decision = promotion.evaluate_promotion(self.obs, prop, claims_by_id, decided_by="human:tester")
        self.assertEqual(decision["decision"], "PROMOTED")
        self.assertEqual(schema.validate_promotion_decision(decision), [])

        promotion.write_to_knowledge_vault(prop, decision)
        from whatsapp.src import ledger as wa_ledger
        entries = wa_ledger.read_all(promotion.KNOWLEDGE_VAULT)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["proposal"]["id"], prop["id"])

    def test_contradicted_claim_defers_before_authority_or_evidence_checked(self):
        prop = proposal.propose_capability(self.obs, self.claim_contradicted, self.rels_by_type["contradicts"], self.candidates_by_id)
        claims_by_id = {self.claim_contradicted["id"]: self.claim_contradicted}
        decision = promotion.evaluate_promotion(self.obs, prop, claims_by_id, decided_by="human:tester")
        self.assertEqual(decision["decision"], "DEFERRED")
        self.assertIn("contradicted-claim", decision["reason"])

    def test_single_source_claim_defers_on_insufficient_evidence(self):
        prop = proposal.propose_capability(self.obs, self.claim_unrelated, self.rels_by_type["unrelated"], self.candidates_by_id)
        claims_by_id = {self.claim_unrelated["id"]: self.claim_unrelated}
        decision = promotion.evaluate_promotion(self.obs, prop, claims_by_id, decided_by="human:tester")
        self.assertEqual(decision["decision"], "DEFERRED")
        self.assertIn("evidence=", decision["reason"])

    def test_never_promoted_without_a_human_decider(self):
        prop = proposal.propose_capability(self.obs, self.claim_corroborated, self.rels_by_type["corroborates"], self.candidates_by_id)
        with self.assertRaises(ValueError):
            promotion.evaluate_promotion(self.obs, prop, {self.claim_corroborated["id"]: self.claim_corroborated}, decided_by="")

    def test_vault_refuses_non_promoted_decisions(self):
        prop = proposal.propose_capability(self.obs, self.claim_unrelated, self.rels_by_type["unrelated"], self.candidates_by_id)
        claims_by_id = {self.claim_unrelated["id"]: self.claim_unrelated}
        decision = promotion.evaluate_promotion(self.obs, prop, claims_by_id, decided_by="human:tester")
        self.assertEqual(decision["decision"], "DEFERRED")
        with self.assertRaises(ValueError):
            promotion.write_to_knowledge_vault(prop, decision)

    def test_promotion_decision_always_human_authored(self):
        prop = proposal.propose_capability(self.obs, self.claim_corroborated, self.rels_by_type["corroborates"], self.candidates_by_id)
        decision = promotion.evaluate_promotion(self.obs, prop, {self.claim_corroborated["id"]: self.claim_corroborated}, decided_by="human:tester")
        self.assertIsNone(decision["provider"])
        self.assertEqual(decision["human_review_status"], "reviewed")
