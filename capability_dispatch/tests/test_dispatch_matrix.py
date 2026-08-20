"""The 12 deterministic tests required by the mission brief (Section 14),
named TEST-DISPATCH-001 through TEST-DISPATCH-012 exactly as specified.
All fixtures are the committed synthetic packet + identity fixtures (see
capability_dispatch/fixtures/); no live network access anywhere (see
base.py's socket.create_connection block, which every test here inherits).
"""
import json
import tempfile
from pathlib import Path

from capability_dispatch.src import dispatch, gate, identity, ingest, overlap, safety_boundary, schema

from .base import CapabilityDispatchTestCase, fixture_path


def _load_identity_fixtures():
    return json.loads(fixture_path("identity_fixtures.json").read_text())


class DispatchMatrixTestCase(CapabilityDispatchTestCase):
    """Shared setUp: ingest the synthetic packet, resolve identity and
    overlap for every candidate, so individual tests can focus on the
    specific behavior they're proving."""

    def setUp(self):
        super().setUp()
        self.src_obs, self.candidates = ingest.ingest_candidate_packet(
            fixture_path("FW-CAP-DISPATCH-004.synthetic.json"), capture_source="test",
        )
        resolver = identity.FixtureIdentityResolver(_load_identity_fixtures())
        self.decided_by = "human:tester"
        self.bundles_by_name = {}
        for cand in self.candidates:
            ev = identity.resolve_identity(
                self.src_obs["source_artifact_id"], self.src_obs["source_artifact_sha256"], cand, resolver,
            )
            updated = identity.apply_identity_evidence(cand, ev)
            ovl = overlap.analyze_overlap(self.src_obs["source_artifact_id"], self.src_obs["source_artifact_sha256"], updated)
            self.bundles_by_name[cand["normalized_name"]] = {
                "candidate": updated, "identity_evidence": ev, "overlap": ovl,
                "profile": None, "verification_results": [],
            }

    def _fully_verify_gitleaks(self):
        b = self.bundles_by_name["synthetic_gitleaks_clone"]
        cid = b["candidate"]["id"]
        b["verification_results"] = [
            schema.new_verification_result(
                artifact_id=self.src_obs["source_artifact_id"], artifact_sha256=self.src_obs["source_artifact_sha256"],
                candidate_id=cid, dimension=d, status="PASSED", basis=f"{d} check passed (fixture)", confidence=0.8,
            )
            for d in ("safety", "license", "maintainability")
        ]
        b["profile"] = schema.new_dispatch_profile(
            artifact_id=self.src_obs["source_artifact_id"], artifact_sha256=self.src_obs["source_artifact_sha256"],
            candidate_id=cid, supported_capability_classes=["secret_scanning_cli"],
            required_execution_surface="isolated_sandbox", permission_surface=["read_files"],
            network_required=False, filesystem_required=True, shell_required=False, credential_required=False,
            context_requirements=[], latency_estimate=2.0, cost_estimate=0.1, reversibility="reversible",
            failure_modes=["scan_timeout"], evidence_strength="SUPPORTED", freshness="unknown", known_conflicts=[],
        )
        return b


class TestDispatch001ValidIntake(DispatchMatrixTestCase):
    """TEST-DISPATCH-001 -- Valid Intake: a valid observation packet
    imports without losing provenance or uncertainty."""

    def test_provenance_preserved(self):
        self.assertEqual(len(self.candidates), 5)
        self.assertTrue(self.src_obs["source_artifact_sha256"])
        self.assertEqual(schema.validate_source_observation(self.src_obs), [])

    def test_uncertainty_preserved_verbatim(self):
        raw_packet = json.loads(fixture_path("FW-CAP-DISPATCH-004.synthetic.json").read_text())
        raw_by_name = {c["observed_name"]: c for c in raw_packet["candidates"]}
        for cand in self.candidates:
            raw_notes = raw_by_name[cand["observed_name"]].get("source_notes", "")
            self.assertEqual(cand["source_notes"], raw_notes, "uncertainty/provenance notes must survive ingestion unaltered")
            self.assertEqual(cand["identity_status"], "UNVERIFIED", "ingestion must not resolve identity itself")


class TestDispatch002MisleadingExtension(CapabilityDispatchTestCase):
    """TEST-DISPATCH-002 -- Misleading Extension: a JPEG payload named
    .png is identified from content rather than extension."""

    def test_jpeg_named_png_detected_by_content(self):
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"NOT_ACTUALLY_A_PNG" * 4
        self.assertEqual(ingest.detect_media_type(jpeg_bytes), "image/jpeg")

    def test_png_named_json_detected_by_content(self):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"NOT_ACTUALLY_JSON" * 4
        self.assertEqual(ingest.detect_media_type(png_bytes), "image/png")

    def test_ingest_refuses_non_json_content_regardless_of_extension(self):
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"PAYLOAD" * 10
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            f.write(jpeg_bytes)
            f.flush()
            with self.assertRaises(ingest.IngestError) as ctx:
                ingest.ingest_candidate_packet(f.name, capture_source="test")
            self.assertIn("image/jpeg", str(ctx.exception))


class TestDispatch003MissingProblemStatement(DispatchMatrixTestCase):
    """TEST-DISPATCH-003 -- Dispatch halts with MISSING_PROBLEM_STATEMENT."""

    def test_halts_with_named_reason(self):
        decision = dispatch.run_dispatch(
            {"mission_id": "FW-CAP-DISPATCH-004", "desired_outcome": "x", "success_metric": "y"},
            run_id="RUN-T3", source_observation=self.src_obs, candidate_bundles=[], decided_by=self.decided_by,
        )
        self.assertEqual(decision["validation_status"], "HARD_BLOCKED")
        self.assertEqual(decision["hard_block_reason"], "MISSING_PROBLEM_STATEMENT")


class TestDispatch004MissingSuccessMetric(DispatchMatrixTestCase):
    """TEST-DISPATCH-004 -- Dispatch halts with MISSING_SUCCESS_METRIC."""

    def test_halts_with_named_reason(self):
        decision = dispatch.run_dispatch(
            {"mission_id": "FW-CAP-DISPATCH-004", "problem_statement": "p", "desired_outcome": "x"},
            run_id="RUN-T4", source_observation=self.src_obs, candidate_bundles=[], decided_by=self.decided_by,
        )
        self.assertEqual(decision["validation_status"], "HARD_BLOCKED")
        self.assertEqual(decision["hard_block_reason"], "MISSING_SUCCESS_METRIC")


class TestDispatch005AmbiguousIdentity(DispatchMatrixTestCase):
    """TEST-DISPATCH-005 -- An unresolved short link cannot become
    installable or dispatch-eligible."""

    def test_shortlink_candidate_is_ambiguous_not_verified(self):
        b = self.bundles_by_name["synthetic_shortlink_mystery_tool"]
        self.assertEqual(b["candidate"]["identity_status"], "AMBIGUOUS")

    def test_shortlink_candidate_blocked_never_selected(self):
        b = self.bundles_by_name["synthetic_shortlink_mystery_tool"]
        ev = dispatch.evaluate_candidate(
            b["candidate"], b["identity_evidence"], b["overlap"], None, [], self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertEqual(ev["disposition"], "BLOCK")
        self.assertEqual(ev["hard_block"]["hard_block_reason"], "IDENTITY_AMBIGUOUS_FOR_INSTALL")

    def test_shortlink_candidate_never_authorized_for_installation(self):
        checklist = safety_boundary.new_gate_checklist()
        checklist["verified_canonical_identity"] = False  # never satisfiable: identity is AMBIGUOUS
        self.assertFalse(safety_boundary.installation_authorized(checklist))


class TestDispatch006MissingAuthority(DispatchMatrixTestCase):
    """TEST-DISPATCH-006 -- A technically capable candidate cannot execute
    without authority."""

    def test_technically_viable_candidate_blocked_without_authority(self):
        b = self._fully_verify_gitleaks()
        # authority_envelope explicitly NOT_GRANTED, everything else ideal
        result = dispatch._classify_disposition(
            b["candidate"], b["identity_evidence"], b["overlap"], b["profile"],
            b["verification_results"], authority_envelope="NOT_GRANTED",
        )
        self.assertEqual(result["disposition"], "BLOCK")
        self.assertEqual(result["hard_block"]["hard_block_reason"], "AUTHORITY_NOT_GRANTED")

    def test_same_candidate_proceeds_once_authority_granted(self):
        b = self._fully_verify_gitleaks()
        result = dispatch._classify_disposition(
            b["candidate"], b["identity_evidence"], b["overlap"], b["profile"],
            b["verification_results"], authority_envelope="GRANTED_BOUNDED",
        )
        self.assertEqual(result["disposition"], "SANDBOX_PROBE")


class TestDispatch007DuplicateCapability(DispatchMatrixTestCase):
    """TEST-DISPATCH-007 -- A popular candidate duplicating an existing
    capability receives DUPLICATE or REUSE_EXISTING."""

    def test_functional_duplicate_receives_duplicate_disposition(self):
        b = self.bundles_by_name["synthetic_python_wrapper_cli"]
        self.assertEqual(b["overlap"]["classification"], "FUNCTIONAL_DUPLICATE")
        ev = dispatch.evaluate_candidate(
            b["candidate"], b["identity_evidence"], b["overlap"], None, [], self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertIn(ev["disposition"], ("DUPLICATE", "REUSE_EXISTING"))

    def test_star_count_never_influences_disposition(self):
        # popularity is not a field on CapabilityCandidate at all --
        # source_notes (where a star-count observation would live) is
        # free text, never read by overlap.py or dispatch.py.
        b = self.bundles_by_name["synthetic_gitleaks_clone"]
        self.assertNotIn("stars", b["candidate"])
        self.assertNotIn("popularity", b["candidate"])
        self.assertIn("star count", b["candidate"]["source_notes"].lower())  # present only as free text


class TestDispatch008UnsafeExecutionSurface(DispatchMatrixTestCase):
    """TEST-DISPATCH-008 -- An unbounded shell, credential, or
    external-action requirement is blocked."""

    def test_unbounded_surface_blocked(self):
        b = self.bundles_by_name["synthetic_unbounded_shell_agent"]
        profile = schema.new_dispatch_profile(
            artifact_id=self.src_obs["source_artifact_id"], artifact_sha256=self.src_obs["source_artifact_sha256"],
            candidate_id=b["candidate"]["id"], supported_capability_classes=["automation_agent"],
            required_execution_surface="full_shell", permission_surface=["shell", "network", "credentials"],
            network_required=True, filesystem_required=True, shell_required=True, credential_required=True,
            context_requirements=[], latency_estimate=1.0, cost_estimate=0.2, reversibility="irreversible",
            failure_modes=["unbounded_side_effects"], evidence_strength="OBSERVED", freshness="unknown", known_conflicts=[],
        )
        self.assertTrue(schema.is_unbounded_execution_surface(profile))
        ev = dispatch.evaluate_candidate(
            b["candidate"], b["identity_evidence"], b["overlap"], profile, [], self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertEqual(ev["disposition"], "BLOCK")
        self.assertEqual(ev["hard_block"]["hard_block_reason"], "UNBOUNDED_EXECUTION_SURFACE")

    def test_reversible_bounded_surface_not_blocked_on_this_ground(self):
        b = self._fully_verify_gitleaks()
        self.assertFalse(schema.is_unbounded_execution_surface(b["profile"]))


class TestDispatch009ValidSandboxProbe(DispatchMatrixTestCase):
    """TEST-DISPATCH-009 -- A verified, authorized, and reversible
    candidate can be routed to an isolated probe without production
    promotion."""

    def test_fully_qualified_candidate_reaches_sandbox_probe(self):
        b = self._fully_verify_gitleaks()
        ev = dispatch.evaluate_candidate(
            b["candidate"], b["identity_evidence"], b["overlap"], b["profile"], b["verification_results"],
            self.decided_by, reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertEqual(ev["disposition"], "SANDBOX_PROBE")
        self.assertIsNone(ev["hard_block"])

    def test_sandbox_probe_never_implies_production_promotion(self):
        b = self._fully_verify_gitleaks()
        self.assertEqual(b["candidate"]["promotion_status"], "NOT_ELIGIBLE")
        self.assertEqual(b["candidate"]["installation_status"], "NOT_INSTALLED")
        # SANDBOX_PROBE disposition never flips these fields itself --
        # only an explicit, separate installation-authority decision
        # (never exercised by this mission) could.
        dispatch.evaluate_candidate(
            b["candidate"], b["identity_evidence"], b["overlap"], b["profile"], b["verification_results"],
            self.decided_by, reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertEqual(b["candidate"]["promotion_status"], "NOT_ELIGIBLE")
        self.assertEqual(b["candidate"]["installation_status"], "NOT_INSTALLED")

    def test_no_installation_authority_checklist_is_ever_satisfied(self):
        checklist = safety_boundary.new_gate_checklist()
        self.assertFalse(safety_boundary.installation_authorized(checklist))


class TestDispatch010SmallestSufficientSet(DispatchMatrixTestCase):
    """TEST-DISPATCH-010 -- The router selects the minimal set satisfying
    all required capabilities."""

    def test_registry_already_covering_requirement_needs_no_candidate(self):
        mission = {
            "mission_id": "FW-CAP-DISPATCH-004", "problem_statement": "need scripting",
            "root_cause_hypothesis": "x", "desired_outcome": "y", "success_metric": "z",
            "required_capabilities": ["scripting_utility"], "authority_envelope": "GRANTED_BOUNDED",
        }
        decision = dispatch.run_dispatch(
            mission, run_id="RUN-T10A", source_observation=self.src_obs,
            candidate_bundles=list(self.bundles_by_name.values()), decided_by=self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertEqual(decision["validation_status"], "DISPATCHED")
        self.assertEqual(len(decision["selected_set"]), 1)
        self.assertEqual(decision["selected_set"][0]["disposition"], "REUSE")
        self.assertIsNone(decision["selected_set"][0]["candidate_id"])

    def test_selected_set_does_not_grow_beyond_what_is_required(self):
        self._fully_verify_gitleaks()
        mission = {
            "mission_id": "FW-CAP-DISPATCH-004", "problem_statement": "need secret scanning",
            "root_cause_hypothesis": "x", "desired_outcome": "y", "success_metric": "z",
            "required_capabilities": ["secret_scanning_cli"], "authority_envelope": "GRANTED_BOUNDED",
        }
        decision = dispatch.run_dispatch(
            mission, run_id="RUN-T10B", source_observation=self.src_obs,
            candidate_bundles=list(self.bundles_by_name.values()), decided_by=self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )
        self.assertEqual(decision["validation_status"], "DISPATCHED")
        # exactly one selection for exactly one required capability --
        # never all 5 ingested candidates, even though all 5 were considered.
        self.assertEqual(len(decision["selected_set"]), 1)
        self.assertEqual(len(decision["considered_candidate_ids"]), 5)


class TestDispatch011EvidenceStateIntegrity(DispatchMatrixTestCase):
    """TEST-DISPATCH-011 -- Unverified observations cannot be promoted to
    verified capability evidence."""

    def test_freshly_ingested_candidates_start_unverified(self):
        for cand in self.candidates:
            self.assertTrue(schema.freshly_ingested_candidate_is_at_epistemic_floor(cand))

    def test_overlap_analysis_refuses_unverified_candidates(self):
        for name in ("synthetic_shortlink_mystery_tool", "synthetic_unknown_tool_xyz"):
            b = self.bundles_by_name[name]
            self.assertNotEqual(b["candidate"]["identity_status"], "VERIFIED")
            self.assertEqual(b["overlap"]["classification"], "UNRESOLVED")
            self.assertEqual(b["overlap"]["recommended_disposition"], "BLOCK")

    def test_no_function_can_set_identity_verified_without_evidence(self):
        # apply_identity_evidence is the ONLY place identity_status can
        # change from UNVERIFIED, and it requires a real IdentityEvidence
        # object whose candidate_id matches.
        cand = self.bundles_by_name["synthetic_unknown_tool_xyz"]["candidate"]
        fake_evidence = {"candidate_id": "CAP-does-not-exist", "resolution": "VERIFIED",
                          "canonical_repository_url": None, "canonical_owner": None, "created_at": "now"}
        with self.assertRaises(ValueError):
            identity.apply_identity_evidence(cand, fake_evidence)


class TestDispatch012RoutingLearning(DispatchMatrixTestCase):
    """TEST-DISPATCH-012 -- Observed execution results update routing
    evidence without rewriting historical records or automatically
    promoting capability authority."""

    def test_learning_record_is_append_only(self):
        from router import mission_router, record_outcome
        from capability_dispatch.src import learning

        b = self._fully_verify_gitleaks()
        mission = {
            "mission_id": "FW-CAP-DISPATCH-004", "problem_statement": "p", "root_cause_hypothesis": "x",
            "desired_outcome": "y", "success_metric": "z", "required_capabilities": ["secret_scanning_cli"],
            "authority_envelope": "GRANTED_BOUNDED",
        }
        decision = dispatch.run_dispatch(
            mission, run_id="RUN-T12", source_observation=self.src_obs,
            candidate_bundles=list(self.bundles_by_name.values()), decided_by=self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )

        pre_existing = record_outcome.HISTORY_PATH.read_text() if record_outcome.HISTORY_PATH.exists() else ""

        learning.record_dispatch_learning(
            artifact_id=self.src_obs["source_artifact_id"], artifact_sha256=self.src_obs["source_artifact_sha256"],
            decision=decision, candidate_id=decision["selected_set"][0]["candidate_id"],
            required_capabilities=mission["required_capabilities"], predicted_utility=0.8, observed_utility=0.75,
            predicted_cost=0.1, observed_cost=0.1, predicted_latency=2.0, observed_latency=2.0,
            expected_outcome="detect fixture secrets", measured_outcome="detected", failure_classification=None,
            rollback_result="not_needed", evidence_sufficiency="SUPPORTED", promotion_decision="NOT_ELIGIBLE",
        )

        after_first = record_outcome.HISTORY_PATH.read_text()
        self.assertTrue(after_first.startswith(pre_existing), "existing history lines must never be rewritten")
        self.assertEqual(len(after_first.splitlines()), len(pre_existing.splitlines()) + 1)

        learning.record_dispatch_learning(
            artifact_id=self.src_obs["source_artifact_id"], artifact_sha256=self.src_obs["source_artifact_sha256"],
            decision=decision, candidate_id=decision["selected_set"][0]["candidate_id"],
            required_capabilities=mission["required_capabilities"], predicted_utility=0.8, observed_utility=0.2,
            predicted_cost=0.1, observed_cost=0.5, predicted_latency=2.0, observed_latency=8.0,
            expected_outcome="detect fixture secrets", measured_outcome="partial failure", failure_classification="EXECUTION_ERROR",
            rollback_result="succeeded", evidence_sufficiency="OBSERVED", promotion_decision="NOT_ELIGIBLE",
        )
        after_second = record_outcome.HISTORY_PATH.read_text()
        self.assertTrue(after_second.startswith(after_first), "the first learning record must survive a second write untouched")
        self.assertEqual(len(after_second.splitlines()), len(pre_existing.splitlines()) + 2)

    def test_learning_never_grants_authority_or_promotion(self):
        from capability_dispatch.src import learning
        from governance.authority import evaluate_authority

        b = self._fully_verify_gitleaks()
        mission = {
            "mission_id": "FW-CAP-DISPATCH-004", "problem_statement": "p", "root_cause_hypothesis": "x",
            "desired_outcome": "y", "success_metric": "z", "required_capabilities": ["secret_scanning_cli"],
            "authority_envelope": "GRANTED_BOUNDED",
        }
        decision = dispatch.run_dispatch(
            mission, run_id="RUN-T12B", source_observation=self.src_obs,
            candidate_bundles=list(self.bundles_by_name.values()), decided_by=self.decided_by,
            reachability_state=self.FIXTURE_REACHABILITY,
        )
        before = evaluate_authority(
            actor_id=self.decided_by, capability=dispatch.SANDBOX_PROBE_CAPABILITY,
            target=dispatch.SANDBOX_PROBE_TARGET, context={"crosses_external_boundary": False},
        )
        learning.record_dispatch_learning(
            artifact_id=self.src_obs["source_artifact_id"], artifact_sha256=self.src_obs["source_artifact_sha256"],
            decision=decision, candidate_id=decision["selected_set"][0]["candidate_id"],
            required_capabilities=mission["required_capabilities"], predicted_utility=0.9, observed_utility=0.9,
            predicted_cost=0.1, observed_cost=0.1, predicted_latency=2.0, observed_latency=2.0,
            expected_outcome="x", measured_outcome="x achieved perfectly", failure_classification=None,
            rollback_result="not_needed", evidence_sufficiency="VALIDATED", promotion_decision="NOT_ELIGIBLE",
        )
        after = evaluate_authority(
            actor_id=self.decided_by, capability=dispatch.SANDBOX_PROBE_CAPABILITY,
            target=dispatch.SANDBOX_PROBE_TARGET, context={"crosses_external_boundary": False},
        )
        self.assertEqual(before.decision, after.decision, "a learning record must never itself change an authority decision")
