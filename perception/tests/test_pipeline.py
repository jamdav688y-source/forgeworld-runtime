from perception.src import ocr, pipeline, retrieval, schema
from perception.tests.base import PerceptionTestCase, fixture_path

FIXTURE_1554_SHA256 = "bec6aac880d86669f459f8f6280da9faa492cf246800fdc25fb3b180ec1efeec"

OCR_TEXT = "GitHub\nPocket Cortex\nInstagram"

RETRIEVAL_FIXTURES = {
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
}


class TestPipeline(PerceptionTestCase):
    def _providers(self):
        ocr_provider = ocr.FixtureOCRProvider({FIXTURE_1554_SHA256: {"text": OCR_TEXT, "confidence": 0.9}})
        retrieval_provider = retrieval.FixtureRetrievalProvider(RETRIEVAL_FIXTURES)
        return ocr_provider, retrieval_provider

    def test_unattended_run_halts_before_promotion(self):
        ocr_provider, retrieval_provider = self._providers()
        result = pipeline.run_pipeline(
            fixture_path("screenshot_1554.png"), "test", ocr_provider, retrieval_provider,
        )
        self.assertEqual(result["observation"]["source_image_sha256"], FIXTURE_1554_SHA256)
        self.assertTrue(len(result["signals"]["entities"]) > 0)
        self.assertTrue(len(result["candidates"]) > 0)
        self.assertTrue(len(result["relationships"]) > 0)
        self.assertTrue(len(result["claims"]) > 0)
        self.assertTrue(all(p["validation_status"] == schema.PROPOSED for p in result["proposals"]))
        self.assertEqual(result["promotion_decisions"], [])  # no decided_by -> no promotion

    def test_attended_run_reaches_mixed_promotion_outcomes(self):
        ocr_provider, retrieval_provider = self._providers()
        result = pipeline.run_pipeline(
            fixture_path("screenshot_1554.png"), "test", ocr_provider, retrieval_provider,
            decided_by="human:tester",
        )
        decisions = {d["decision"] for d in result["promotion_decisions"]}
        self.assertIn("PROMOTED", decisions)
        self.assertIn("DEFERRED", decisions)
        for d in result["promotion_decisions"]:
            self.assertEqual(schema.validate_promotion_decision(d), [])

    def test_output_distinguishes_observation_inference_validation_promotion(self):
        # mission acceptance test, verbatim: "Final output distinguishes
        # observation, inference, validation, and promotion."
        ocr_provider, retrieval_provider = self._providers()
        result = pipeline.run_pipeline(
            fixture_path("screenshot_1554.png"), "test", ocr_provider, retrieval_provider,
            decided_by="human:tester",
        )
        self.assertIn("observation", result)  # OBSERVATION
        self.assertIn("candidates", result)  # INFERENCE (unvalidated retrieval results)
        self.assertIn("relationships", result)  # VALIDATION (independence-checked)
        self.assertIn("claims", result)  # VALIDATION (evidence-classified)
        self.assertIn("proposals", result)  # PROMOTION (proposed)
        self.assertIn("promotion_decisions", result)  # PROMOTION (decided)
        # candidates never carry a stronger validation_status than CANDIDATE_MATCH on their own
        self.assertTrue(all(c["validation_status"] == schema.CANDIDATE_MATCH for c in result["candidates"]))

    def test_contradictions_remain_visible_and_unresolved(self):
        # mission acceptance test, verbatim: "Contradictory candidates
        # remain visible and unresolved."
        ocr_provider, retrieval_provider = self._providers()
        result = pipeline.run_pipeline(
            fixture_path("screenshot_1554.png"), "test", ocr_provider, retrieval_provider,
            decided_by="human:tester",
        )
        self.assertTrue(len(result["contradictions"]) > 0)
        for c in result["contradictions"]:
            self.assertEqual(c["validation_status"], "unresolved")
            self.assertEqual(c["contradiction_state"], "active")
