from perception.src import entities, ingest, ocr, retrieval, schema
from perception.tests.base import PerceptionTestCase, fixture_path


class TestRegistry(PerceptionTestCase):
    def test_registry_loads_and_has_expected_connectors(self):
        reg = retrieval.load_registry()
        ids = {c["id"] for c in reg}
        self.assertEqual(ids, {"fixture_retrieval", "web_search_unwired"})

    def test_probe_registry_reuses_capabilities_discover(self):
        probe = retrieval.probe_registry()
        self.assertEqual(probe["fixture_retrieval"]["reachability_confidence"], 1.0)
        self.assertEqual(probe["web_search_unwired"]["reachability_confidence"], 0.0)


class TestRetrieveCandidates(PerceptionTestCase):
    def setUp(self):
        super().setUp()
        self.obs = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        image_bytes = fixture_path("screenshot_1554.png").read_bytes()
        ocr_provider = ocr.FixtureOCRProvider({self.obs["source_image_sha256"]: {"text": "GitHub", "confidence": 0.9}})
        self.ocr_signal = ocr.extract_ocr_signal(self.obs, image_bytes, ocr_provider)
        self.entity_signal = entities.extract_entities(self.obs, self.ocr_signal)[0]

    def test_every_candidate_starts_as_candidate_match(self):
        provider = retrieval.FixtureRetrievalProvider({
            "GitHub": [{"url": "https://github.com", "title": "GitHub", "snippet": "x", "confidence": 0.7}]
        })
        candidates = retrieval.retrieve_candidates(self.obs, [self.entity_signal], provider)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["validation_status"], schema.CANDIDATE_MATCH)
        self.assertEqual(schema.validate_candidate_source(candidates[0]), [])

    def test_empty_query_entity_is_skipped_without_crashing(self):
        weird_signal = dict(self.entity_signal)
        weird_signal["value"] = {"entity_type": "platform_name", "text": ""}
        provider = retrieval.FixtureRetrievalProvider({})
        candidates = retrieval.retrieve_candidates(self.obs, [weird_signal], provider)
        self.assertEqual(candidates, [])

    def test_unregistered_query_returns_no_candidates(self):
        provider = retrieval.FixtureRetrievalProvider({})
        candidates = retrieval.retrieve_candidates(self.obs, [self.entity_signal], provider)
        self.assertEqual(candidates, [])

    def test_unwired_web_search_provider_raises(self):
        with self.assertRaises(NotImplementedError):
            retrieval.retrieve_candidates(self.obs, [self.entity_signal], retrieval.WebSearchProvider())
