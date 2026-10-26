from perception.src import entities, ingest, ocr, schema
from perception.tests.base import PerceptionTestCase, fixture_path


class TestOCR(PerceptionTestCase):
    def setUp(self):
        super().setUp()
        self.obs = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        self.image_bytes = fixture_path("screenshot_1554.png").read_bytes()

    def test_fixture_provider_returns_registered_text(self):
        provider = ocr.FixtureOCRProvider({
            self.obs["source_image_sha256"]: {"text": "ForgeWorld Runtime", "confidence": 0.93}
        })
        sig = ocr.extract_ocr_signal(self.obs, self.image_bytes, provider)
        self.assertEqual(sig["value"], "ForgeWorld Runtime")
        self.assertEqual(sig["confidence"], 0.93)
        self.assertEqual(sig["provider"], "mock:fixture_ocr")
        self.assertEqual(schema.validate_extracted_signal(sig), [])

    def test_unregistered_sha256_yields_empty_text_not_fabricated(self):
        provider = ocr.FixtureOCRProvider({})
        sig = ocr.extract_ocr_signal(self.obs, self.image_bytes, provider)
        self.assertEqual(sig["value"], "")
        self.assertEqual(sig["confidence"], 0.0)

    def test_unwired_cloud_provider_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            ocr.extract_ocr_signal(self.obs, self.image_bytes, ocr.CloudOCRProvider())

    def test_fingerprint_signal_is_deterministic_and_provider_free(self):
        sig1 = ocr.extract_fingerprint_signal(self.obs, self.image_bytes)
        sig2 = ocr.extract_fingerprint_signal(self.obs, self.image_bytes)
        self.assertEqual(sig1["value"], sig2["value"])
        self.assertIsNone(sig1["provider"])
        self.assertEqual(sig1["confidence"], 1.0)
        self.assertEqual(schema.validate_extracted_signal(sig1), [])


class TestEntities(PerceptionTestCase):
    def setUp(self):
        super().setUp()
        self.obs = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        self.image_bytes = fixture_path("screenshot_1554.png").read_bytes()

    def _ocr_signal(self, text):
        provider = ocr.FixtureOCRProvider({self.obs["source_image_sha256"]: {"text": text, "confidence": 0.9}})
        return ocr.extract_ocr_signal(self.obs, self.image_bytes, provider)

    def test_extracts_recognizable_platform_names_and_page_title(self):
        # mission acceptance test, verbatim: "OCR extracts recognizable
        # platform names and visible page titles."
        ocr_sig = self._ocr_signal("Pocket Cortex\nWhatsApp Intelligence Membrane\nGitHub — forgeworld-runtime")
        sigs = entities.extract_entities(self.obs, ocr_sig)
        for s in sigs:
            self.assertEqual(schema.validate_extracted_signal(s), [])

        platform_names = {s["value"]["text"] for s in sigs if s["value"]["entity_type"] == "platform_name"}
        self.assertIn("WhatsApp", platform_names)
        self.assertIn("GitHub", platform_names)
        self.assertIn("Pocket Cortex", platform_names)

        page_titles = [s["value"]["text"] for s in sigs if s["value"]["entity_type"] == "page_title"]
        self.assertEqual(page_titles, ["WhatsApp Intelligence Membrane"])  # the longest line

    def test_short_platform_name_does_not_false_positive_inside_unrelated_word(self):
        # regression test: "X" (Twitter/X) previously matched naively as a
        # substring inside "Cortex" via `"x" in "cortex"`. Fixed with
        # word-boundary regex matching in entities.py.
        ocr_sig = self._ocr_signal("Pocket Cortex")
        sigs = entities.extract_entities(self.obs, ocr_sig)
        names = [s["value"]["text"] for s in sigs if s["value"]["entity_type"] == "platform_name"]
        self.assertNotIn("X", names)

    def test_standalone_short_platform_name_still_matches(self):
        ocr_sig = self._ocr_signal("Follow us on X for updates")
        sigs = entities.extract_entities(self.obs, ocr_sig)
        names = [s["value"]["text"] for s in sigs if s["value"]["entity_type"] == "platform_name"]
        self.assertIn("X", names)

    def test_empty_ocr_text_yields_no_fabricated_entities(self):
        ocr_sig = self._ocr_signal("")
        self.assertEqual(entities.extract_entities(self.obs, ocr_sig), [])

    def test_entity_signals_reference_both_observation_and_ocr_signal(self):
        ocr_sig = self._ocr_signal("GitHub")
        sigs = entities.extract_entities(self.obs, ocr_sig)
        for s in sigs:
            self.assertIn(self.obs["id"], s["evidence_references"])
            self.assertIn(ocr_sig["id"], s["evidence_references"])
