from perception.src import claims, corroboration, entities, ingest, ocr, retrieval, schema
from perception.tests.base import PerceptionTestCase, fixture_path


class _PipelineFixtureMixin:
    def setUp(self):
        super().setUp()
        self.obs = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        self.image_bytes = fixture_path("screenshot_1554.png").read_bytes()
        ocr_provider = ocr.FixtureOCRProvider({
            self.obs["source_image_sha256"]: {"text": "GitHub\nPocket Cortex\nInstagram", "confidence": 0.9}
        })
        ocr_signal = ocr.extract_ocr_signal(self.obs, self.image_bytes, ocr_provider)
        entity_signals = entities.extract_entities(self.obs, ocr_signal)
        self.by_text = {s["value"]["text"]: s for s in entity_signals if s["value"]["entity_type"] == "platform_name"}

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
        self.candidates = (
            retrieval.retrieve_candidates(self.obs, [self.by_text["GitHub"]], retrieval_provider)
            + retrieval.retrieve_candidates(self.obs, [self.by_text["Pocket Cortex"]], retrieval_provider)
            + retrieval.retrieve_candidates(self.obs, [self.by_text["Instagram"]], retrieval_provider)
        )


class TestCorroboration(_PipelineFixtureMixin, PerceptionTestCase):
    def test_independent_agreeing_domains_corroborate(self):
        result = corroboration.assess_corroboration(self.obs, self.candidates)
        types = {r["relationship_type"] for r in result["relationships"]}
        self.assertIn("corroborates", types)
        for r in result["relationships"]:
            self.assertEqual(schema.validate_evidence_relationship(r), [])

    def test_disputed_independent_domains_produce_unresolved_contradiction(self):
        result = corroboration.assess_corroboration(self.obs, self.candidates)
        self.assertIn("contradicts", {r["relationship_type"] for r in result["relationships"]})
        self.assertEqual(len(result["contradictions"]), 1)
        ctr = result["contradictions"][0]
        self.assertEqual(ctr["validation_status"], "unresolved")
        self.assertEqual(ctr["contradiction_state"], "active")
        self.assertEqual(schema.validate_contradiction_record(ctr), [])

    def test_single_domain_group_is_unrelated_not_independent(self):
        result = corroboration.assess_corroboration(self.obs, self.candidates)
        self.assertIn("unrelated", {r["relationship_type"] for r in result["relationships"]})

    def test_cross_observation_near_duplicate(self):
        obs_1555 = ingest.ingest_image(fixture_path("screenshot_1555.png"), capture_source="test")
        fp_1554 = ocr.extract_fingerprint_signal(self.obs, self.image_bytes)
        fp_1555 = ocr.extract_fingerprint_signal(obs_1555, fixture_path("screenshot_1555.png").read_bytes())

        rel = corroboration.compare_observation_fingerprints(self.obs, fp_1554, obs_1555, fp_1555)
        self.assertIsNotNone(rel)
        self.assertEqual(rel["relationship_type"], "near_duplicate")
        self.assertEqual(schema.validate_evidence_relationship(rel), [])
        self.assertNotEqual(self.obs["source_image_sha256"], obs_1555["source_image_sha256"])

    def test_genuinely_different_images_are_not_forced_into_a_relationship(self):
        obs_diff = ingest.ingest_image(fixture_path("screenshot_different.png"), capture_source="test")
        fp_1554 = ocr.extract_fingerprint_signal(self.obs, self.image_bytes)
        fp_diff = ocr.extract_fingerprint_signal(obs_diff, fixture_path("screenshot_different.png").read_bytes())
        rel = corroboration.compare_observation_fingerprints(self.obs, fp_1554, obs_diff, fp_diff)
        self.assertIsNone(rel)

    def test_self_comparison_refused(self):
        fp = ocr.extract_fingerprint_signal(self.obs, self.image_bytes)
        with self.assertRaises(ValueError):
            corroboration.compare_observation_fingerprints(self.obs, fp, self.obs, fp)


class TestClaimsAndEvidenceClassification(_PipelineFixtureMixin, PerceptionTestCase):
    def _relationship_and_signal(self, relationship_type):
        result = corroboration.assess_corroboration(self.obs, self.candidates)
        rel = next(r for r in result["relationships"] if r["relationship_type"] == relationship_type)
        anchor = next(c for c in self.candidates if c["id"] in rel["evidence_references"])
        entity_signal_id = anchor["evidence_references"][0]
        signal = next(s for s in self.by_text.values() if s["id"] == entity_signal_id)
        return rel, signal

    def test_corroborates_maps_to_corroborated_claim(self):
        rel, signal = self._relationship_and_signal("corroborates")
        claim = claims.extract_claim(self.obs, signal, rel)
        self.assertEqual(claim["validation_status"], "corroborated-claim")
        self.assertEqual(schema.validate_extracted_claim(claim), [])

    def test_contradicts_maps_to_contradicted_claim(self):
        rel, signal = self._relationship_and_signal("contradicts")
        claim = claims.extract_claim(self.obs, signal, rel)
        self.assertEqual(claim["validation_status"], "contradicted-claim")

    def test_unrelated_maps_to_unverified_claim(self):
        rel, signal = self._relationship_and_signal("unrelated")
        claim = claims.extract_claim(self.obs, signal, rel)
        self.assertEqual(claim["validation_status"], "unverified-claim")

    def test_claim_references_its_relationship(self):
        rel, signal = self._relationship_and_signal("corroborates")
        claim = claims.extract_claim(self.obs, signal, rel)
        self.assertIn(rel["id"], claim["evidence_references"])
