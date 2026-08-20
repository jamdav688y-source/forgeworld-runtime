"""Tests for the AUTHORITATIVE FW-CAP-DISPATCH-004 packet
(capability_dispatch/intake/FW-CAP-DISPATCH-004.json/.md, committed by the
repository owner at 611b41ef8cc4c1bd1837c054aa69a8183e17fe26). Hash-pinned:
if these files are ever accidentally edited, this suite fails loudly
rather than silently validating different content than what was reviewed.

Distinct from test_dispatch_matrix.py, which exercises the deterministic
TEST_FIXTURE synthetic packet -- this file is the one that proves the
real-shape parser (authoritative_intake.py) actually works against the
real, differently-shaped artifact.
"""
from pathlib import Path

from capability_dispatch.src import authoritative_intake, dispatch, gate, identity, overlap, schema
from capability_dispatch.tests.base import CapabilityDispatchTestCase

INTAKE_DIR = Path(__file__).resolve().parent.parent / "intake"
JSON_PATH = INTAKE_DIR / "FW-CAP-DISPATCH-004.json"
MD_PATH = INTAKE_DIR / "FW-CAP-DISPATCH-004.md"

EXPECTED_JSON_SHA256 = "8252cf225ad9017c33f7bbadbcaba1d0e65e0a86a6231376a1b536f066798e1f"
EXPECTED_MD_SHA256 = "b696b375f3921b185017c912d3a3ce5583db71d57db5af53136c4350d358a07b"


class TestAuthoritativeArtifactsExistAndHashMatch(CapabilityDispatchTestCase):
    def test_files_exist(self):
        self.assertTrue(JSON_PATH.is_file(), f"missing: {JSON_PATH}")
        self.assertTrue(MD_PATH.is_file(), f"missing: {MD_PATH}")

    def test_hashes_match_the_declared_authoritative_values(self):
        from capability_dispatch.src.common import sha256_hex
        self.assertEqual(sha256_hex(JSON_PATH.read_bytes()), EXPECTED_JSON_SHA256)
        self.assertEqual(sha256_hex(MD_PATH.read_bytes()), EXPECTED_MD_SHA256)


class TestAuthoritativeIngestion(CapabilityDispatchTestCase):
    def setUp(self):
        super().setUp()
        self.result = authoritative_intake.ingest_authoritative_packet(
            JSON_PATH, MD_PATH, capture_source="test",
        )

    def test_hashes_recorded_on_the_source_observation_match_independently_computed_values(self):
        self.assertEqual(self.result["source_observation"]["source_artifact_sha256"], EXPECTED_JSON_SHA256)
        self.assertEqual(self.result["md_source_observation"]["source_artifact_sha256"], EXPECTED_MD_SHA256)

    def test_exactly_42_candidates_extracted(self):
        self.assertEqual(len(self.result["candidates"]), 42)
        self.assertEqual(self.result["source_observation"]["candidate_count"], 42)

    def test_candidate_count_is_marked_as_derived_not_declared(self):
        self.assertIn("derived", self.result["source_observation"]["source_notes"])

    def test_every_candidate_valid_and_at_epistemic_floor(self):
        for c in self.result["candidates"]:
            self.assertEqual(schema.validate_capability_candidate(c), [])
            self.assertTrue(schema.freshly_ingested_candidate_is_at_epistemic_floor(c))

    def test_no_duplicate_names(self):
        names = [c["observed_name"].lower() for c in self.result["candidates"]]
        self.assertEqual(len(names), len(set(names)))

    def test_observed_name_kept_separate_from_normalized_name(self):
        ecc = next(c for c in self.result["candidates"] if c["observed_name"] == "ECC")
        self.assertNotEqual(ecc["observed_name"], ecc["normalized_name"])
        self.assertEqual(ecc["normalized_name"], "ecc")

    def test_bare_canonical_hints_preserved_raw_and_separately_normalized(self):
        ecc = next(c for c in self.result["candidates"] if c["observed_name"] == "ECC")
        self.assertEqual(ecc["canonical_hint"], "github.com/affaan-m/ECC")  # raw, unmodified
        self.assertEqual(ecc["canonical_hint_normalized"], "https://github.com/affaan-m/ECC")
        self.assertEqual(ecc["canonical_hint_normalization_method"], "assumed_https_scheme_prepended_to_bare_domain_path")

    def test_candidates_without_a_hint_keep_it_as_none_never_guessed(self):
        cc_switch = next(c for c in self.result["candidates"] if c["observed_name"] == "cc-switch")
        self.assertIsNone(cc_switch["canonical_hint"])
        self.assertIsNone(cc_switch["canonical_hint_normalized"])

    def test_nine_candidates_carry_a_hint(self):
        with_hints = [c for c in self.result["candidates"] if c["canonical_hint"]]
        self.assertEqual(len(with_hints), 9)

    def test_strategy_signals_and_source_observations_preserved_verbatim(self):
        self.assertEqual(len(self.result["strategy_signals_raw"]), 1)
        self.assertEqual(self.result["strategy_signals_raw"][0]["signal_id"], "FW-SIGNAL-PROBLEM-FIRST-001")
        self.assertEqual(len(self.result["source_observations_raw"]), 3)


class TestAuthoritativeFullPipeline(CapabilityDispatchTestCase):
    """Runs identity resolution (empty fixture -- no live network), overlap
    analysis, and dispatch against all 42 real candidates -- the honest
    all-UNAVAILABLE / all-UNRESOLVED / all-BLOCK outcome this mission's
    offline constraint produces, matching identity_resolution_report.json.
    """

    def setUp(self):
        super().setUp()
        self.result = authoritative_intake.ingest_authoritative_packet(JSON_PATH, MD_PATH, capture_source="test")
        self.resolver = identity.FixtureIdentityResolver({})  # no live lookup this mission

    def test_all_42_resolve_unavailable_offline(self):
        for c in self.result["candidates"]:
            ev = identity.resolve_identity(
                self.result["source_observation"]["source_artifact_id"],
                self.result["source_observation"]["source_artifact_sha256"], c, self.resolver,
            )
            self.assertEqual(ev["resolution"], "UNAVAILABLE")
            self.assertEqual(schema.validate_identity_evidence(ev), [])

    def test_all_42_overlap_unresolved_as_a_consequence(self):
        for c in self.result["candidates"]:
            ev = identity.resolve_identity(
                self.result["source_observation"]["source_artifact_id"],
                self.result["source_observation"]["source_artifact_sha256"], c, self.resolver,
            )
            updated = identity.apply_identity_evidence(c, ev)
            ovl = overlap.analyze_overlap(
                self.result["source_observation"]["source_artifact_id"],
                self.result["source_observation"]["source_artifact_sha256"], updated,
            )
            self.assertEqual(ovl["classification"], "UNRESOLVED")

    def test_dispatch_without_mission_fields_hard_blocks(self):
        decision = dispatch.run_dispatch(
            {"mission_id": "FW-CAP-DISPATCH-004"}, run_id="RUN-TEST-AUTH-HB",
            source_observation=self.result["source_observation"], candidate_bundles=[],
            decided_by="human:tester",
        )
        self.assertEqual(decision["validation_status"], "HARD_BLOCKED")
        self.assertEqual(decision["hard_block_reason"], "MISSING_PROBLEM_STATEMENT")

    def test_full_dispatch_reaches_no_sufficient_candidate_honestly(self):
        bundles = []
        for c in self.result["candidates"]:
            ev = identity.resolve_identity(
                self.result["source_observation"]["source_artifact_id"],
                self.result["source_observation"]["source_artifact_sha256"], c, self.resolver,
            )
            updated = identity.apply_identity_evidence(c, ev)
            ovl = overlap.analyze_overlap(
                self.result["source_observation"]["source_artifact_id"],
                self.result["source_observation"]["source_artifact_sha256"], updated,
            )
            bundles.append({"candidate": updated, "identity_evidence": ev, "overlap": ovl, "profile": None, "verification_results": []})

        mission_request = {
            "mission_id": "FW-CAP-DISPATCH-004",
            "problem_statement": "test: evaluate the 42 observed candidates",
            "desired_outcome": "a disposition for each",
            "success_metric": "every candidate receives a recorded reason",
            "required_capabilities": sorted({c["normalized_category"] for c in self.result["candidates"]}),
            "authority_envelope": "GRANTED_BOUNDED",
        }
        decision = dispatch.run_dispatch(
            mission_request, run_id="RUN-TEST-AUTH-FULL",
            source_observation=self.result["source_observation"], candidate_bundles=bundles,
            decided_by="human:tester", reachability_state=self.FIXTURE_REACHABILITY,
        )
        # every candidate individually BLOCKed on identity
        for b in bundles:
            ev = dispatch.evaluate_candidate(
                b["candidate"], b["identity_evidence"], b["overlap"], None, [], "human:tester",
                reachability_state=self.FIXTURE_REACHABILITY,
            )
            self.assertEqual(ev["disposition"], "BLOCK")
            self.assertEqual(ev["hard_block"]["hard_block_reason"], "IDENTITY_AMBIGUOUS_FOR_INSTALL")
        # some required capabilities are covered by the EXISTING registry
        # (REUSE, no new candidate) -- proving smallest-sufficient-set logic
        # engages real registry data, not just newly ingested candidates.
        reuse_entries = [s for s in decision["selected_set"] if s.get("existing_capability_id")]
        self.assertTrue(reuse_entries)
        self.assertEqual(schema.validate_dispatch_decision(decision), [])

    def test_no_candidate_ever_installed_cloned_or_executed(self):
        # structural: this test file itself never imports subprocess/os.system/etc,
        # and neither does authoritative_intake.py -- see safety_boundary tests.
        import capability_dispatch.src.authoritative_intake as mod
        source = Path(mod.__file__).read_text()
        for forbidden in ("subprocess", "os.system", "os.popen"):
            self.assertNotIn(forbidden, source)
