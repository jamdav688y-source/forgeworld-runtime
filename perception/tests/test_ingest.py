import tempfile
from pathlib import Path

from perception.src import ingest, schema
from perception.tests.base import PerceptionTestCase, fixture_path


class TestIngest(PerceptionTestCase):
    def test_ingest_produces_valid_hash_verified_observation(self):
        obs = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        self.assertEqual(schema.validate_visual_observation(obs), [])
        self.assertEqual(obs["validation_status"], "hash_verified")
        self.assertEqual(obs["confidence"], 1.0)
        self.assertEqual(obs["width"], 64)
        self.assertEqual(obs["height"], 64)

    def test_ingest_is_idempotent_by_content_hash(self):
        obs1 = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        obs2 = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        self.assertEqual(obs1["source_image_sha256"], obs2["source_image_sha256"])
        stored = ingest.stored_image_path(obs1["source_image_sha256"])
        self.assertTrue(stored.exists())

    def test_ingest_never_modifies_the_source_file(self):
        src = fixture_path("screenshot_1554.png")
        original_bytes = src.read_bytes()
        ingest.ingest_image(src, capture_source="test")
        self.assertEqual(src.read_bytes(), original_bytes)

    def test_missing_file_fails_closed(self):
        with self.assertRaises(ingest.IngestError):
            ingest.ingest_image("/nonexistent/path/does-not-exist.png", capture_source="test")

    def test_empty_file_fails_closed(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            with self.assertRaises(ingest.IngestError):
                ingest.ingest_image(f.name, capture_source="test")

    def test_non_png_bytes_fail_closed(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            f.write(b"not a real png file")
            f.flush()
            with self.assertRaises(ingest.IngestError):
                ingest.ingest_image(f.name, capture_source="test")

    def test_stored_image_path_raises_for_unknown_sha256(self):
        with self.assertRaises(ingest.IngestError):
            ingest.stored_image_path("f" * 64)

    def test_two_different_fixtures_get_different_observations(self):
        obs_a = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        obs_b = ingest.ingest_image(fixture_path("screenshot_different.png"), capture_source="test")
        self.assertNotEqual(obs_a["source_image_sha256"], obs_b["source_image_sha256"])
        self.assertNotEqual(obs_a["id"], obs_b["id"])
