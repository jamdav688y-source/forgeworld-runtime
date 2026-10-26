import unittest

from perception.src import common, schema


class TestEnvelope(unittest.TestCase):
    def test_new_id_prefixed_and_unique(self):
        a, b = common.new_id("OBS"), common.new_id("OBS")
        self.assertTrue(a.startswith("OBS-"))
        self.assertNotEqual(a, b)

    def test_sha256_hex_is_64_lowercase_hex(self):
        digest = common.sha256_hex(b"hello world")
        self.assertEqual(len(digest), 64)
        self.assertTrue(common.HEX64.match(digest))

    def test_build_envelope_rejects_both_raw_response_and_hash(self):
        with self.assertRaises(ValueError):
            common.build_envelope(
                "X", "img", "a" * 64, "method", "status",
                raw_response={"a": 1}, raw_response_hash="b" * 64,
            )


class TestEightObjects(unittest.TestCase):
    """One end-to-end chain through all 8 required objects, each validated
    immediately after construction -- the exact chain smoke-tested by hand
    while building schema.py, now committed as a real, re-runnable test."""

    def test_full_chain_validates_with_zero_errors(self):
        obs = schema.new_visual_observation(
            image_id="IMG-test", image_sha256="a" * 64, width=10, height=10,
            file_size_bytes=100, mime_type="image/png", capture_source="test",
        )
        self.assertEqual(schema.validate_visual_observation(obs), [])

        sig = schema.new_extracted_signal(
            image_id="IMG-test", image_sha256="a" * 64, signal_type="ocr_text",
            value="hello", extraction_method="ocr", provider="mock", confidence=0.9,
            observation_id=obs["id"],
        )
        self.assertEqual(schema.validate_extracted_signal(sig), [])

        cand = schema.new_candidate_source(
            image_id="IMG-test", image_sha256="a" * 64, provider="mock",
            url="https://example.com", title="Example", snippet="snip",
            retrieval_confidence=0.5, query_signal_ids=[sig["id"]],
        )
        self.assertEqual(cand["validation_status"], schema.CANDIDATE_MATCH)
        self.assertEqual(schema.validate_candidate_source(cand), [])

        rel = schema.new_evidence_relationship(
            image_id="IMG-test", image_sha256="a" * 64, relationship_type="corroborates",
            candidate_ids=[cand["id"]], independence_basis="test basis", confidence=0.7,
        )
        self.assertEqual(schema.validate_evidence_relationship(rel), [])

        claim = schema.new_extracted_claim(
            image_id="IMG-test", image_sha256="a" * 64, claim_text="X is true",
            claim_subject="X", claim_predicate="is true", relationship_ids=[rel["id"]],
            confidence=0.6,
        )
        self.assertEqual(schema.validate_extracted_claim(claim), [])

        ctr = schema.new_contradiction_record(
            image_id="IMG-test", image_sha256="a" * 64, description="disagreement",
            conflicting_ids=[cand["id"], rel["id"]],
        )
        self.assertEqual(ctr["validation_status"], "unresolved")
        self.assertEqual(ctr["contradiction_state"], "active")
        self.assertEqual(schema.validate_contradiction_record(ctr), [])

        prop = schema.new_capability_proposal(
            image_id="IMG-test", image_sha256="a" * 64,
            proposed_capability_text="X", rationale="because Y",
            claim_ids=[claim["id"]], confidence=0.6,
        )
        self.assertEqual(prop["validation_status"], schema.PROPOSED)
        self.assertEqual(schema.validate_capability_proposal(prop), [])

        promo = schema.new_promotion_decision(
            image_id="IMG-test", image_sha256="a" * 64, proposal_id=prop["id"],
            decision="PROMOTED", decided_by="human:tester", reason="ok",
            authority_decision="HUMAN_ONLY", evidence_state="SUPPORTED",
        )
        self.assertIsNone(promo["provider"])
        self.assertEqual(promo["human_review_status"], "reviewed")
        self.assertEqual(schema.validate_promotion_decision(promo), [])

    def test_capability_proposal_validation_status_cannot_be_anything_but_proposed(self):
        prop = schema.new_capability_proposal(
            image_id="IMG-test", image_sha256="a" * 64,
            proposed_capability_text="X", rationale="Y", claim_ids=["CLM-1"], confidence=0.5,
        )
        prop["validation_status"] = "VALIDATED"  # simulate a bug trying to self-validate
        errors = schema.validate_capability_proposal(prop)
        self.assertTrue(any("may not self-validate" in e for e in errors))

    def test_promotion_decision_rejects_non_null_provider(self):
        promo = schema.new_promotion_decision(
            image_id="IMG-test", image_sha256="a" * 64, proposal_id="PRP-1",
            decision="PROMOTED", decided_by="human:tester", reason="ok",
            authority_decision="HUMAN_ONLY", evidence_state="SUPPORTED",
        )
        promo["provider"] = "some-model"  # simulate a bug: a model claiming authorship
        errors = schema.validate_promotion_decision(promo)
        self.assertTrue(any("only a human may author" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
