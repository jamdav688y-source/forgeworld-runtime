"""CapabilityGraph, WorkflowCompiler, CapabilityFoundry, and
CapabilityPromotionGate tests (Sections 8-10, 15), including restart/
persistence (Section 30)."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import interface as si


class TestCapabilityGraphLifecycle(unittest.TestCase):
    def test_new_capability_starts_discovered_and_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("widget_maker", display_name="Widget Maker", description="makes widgets")
            record = cg.resolve_current("widget_maker")
            self.assertEqual(record["lifecycle_state"], si.CAP_STATE_DISCOVERED)
            self.assertFalse(cg.is_available("widget_maker"))

    def test_cannot_register_same_capability_id_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("widget_maker", display_name="x", description="y")
            with self.assertRaises(si.SubstrateError):
                cg.register_discovered("widget_maker", display_name="x", description="y")

    def test_dependencies_gate_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("base_cap", display_name="Base", description="base")
            cg.register_discovered("composite_cap", display_name="Composite", description="needs base", requires_capability_ids=("base_cap",))
            for dim in ("TECHNICAL", "GOVERNANCE"):
                cg.record_evidence_dimension("composite_cap", dim, si.DIM_EVIDENCED)
                cg.record_evidence_dimension("base_cap", dim, si.DIM_EVIDENCED)
            gate = si.CapabilityPromotionGate()
            gate.apply_promotion(cg, gate.evaluate(cg.resolve_current("composite_cap"), si.CAP_STATE_DEMONSTRATED))
            # composite_cap is itself DEMONSTRATED but base_cap is still DISCOVERED
            self.assertTrue(cg.is_available("composite_cap"))
            self.assertFalse(cg.dependencies_satisfied("composite_cap"))
            gate.apply_promotion(cg, gate.evaluate(cg.resolve_current("base_cap"), si.CAP_STATE_DEMONSTRATED))
            self.assertTrue(cg.dependencies_satisfied("composite_cap"))

    def test_survives_restart_lifecycle_state_and_reason_reconstructable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg1 = si.CapabilityGraph(tmp)
            cg1.register_discovered("durable_cap", display_name="x", description="y")
            cg1.record_evidence_dimension("durable_cap", "TECHNICAL", si.DIM_EVIDENCED)
            cg1.record_evidence_dimension("durable_cap", "GOVERNANCE", si.DIM_EVIDENCED)
            gate = si.CapabilityPromotionGate()
            decision = gate.evaluate(cg1.resolve_current("durable_cap"), si.CAP_STATE_DEMONSTRATED)
            gate.apply_promotion(cg1, decision)
            version_before_restart = cg1.version()

            # Fresh CapabilityGraph object, same directory -- simulates a
            # process restart reading only durable state off disk.
            cg2 = si.CapabilityGraph(tmp)
            record = cg2.resolve_current("durable_cap")
            self.assertEqual(record["lifecycle_state"], si.CAP_STATE_DEMONSTRATED)
            self.assertIn(decision.decision_id, record["reason"])
            self.assertEqual(cg2.version(), version_before_restart)


class TestWorkflowCompiler(unittest.TestCase):
    def _graph_with(self, tmp, capability_id, state=None):
        cg = si.CapabilityGraph(Path(tmp))
        cg.register_discovered(capability_id, display_name=capability_id, description=capability_id)
        if state is not None:
            for dim in si.DEFAULT_PROMOTION_POLICY[state]:
                cg.record_evidence_dimension(capability_id, dim, si.DIM_EVIDENCED)
            gate = si.CapabilityPromotionGate()
            gate.apply_promotion(cg, gate.evaluate(cg.resolve_current(capability_id), state))
        return cg

    def test_existing_capability_is_directly_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = self._graph_with(tmp, "physical_ping", si.CAP_STATE_DEMONSTRATED)
            obj = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("physical_ping",), authority_ceiling=("physical_ping",),
            )
            plan, gaps = si.WorkflowCompiler().compile(obj, cg)
            self.assertEqual(plan.existing_capability_ids, ("physical_ping",))
            self.assertEqual(plan.missing_capability_ids, ())
            self.assertEqual(gaps, ())
            self.assertTrue(plan.is_executable)

    def test_missing_capability_becomes_a_gap_never_hallucinated(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))  # empty graph
            obj = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("nonexistent_cap",), authority_ceiling=("nonexistent_cap",),
            )
            plan, gaps = si.WorkflowCompiler().compile(obj, cg)
            self.assertEqual(plan.missing_capability_ids, ("nonexistent_cap",))
            self.assertFalse(plan.is_executable)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0].missing_capability_id, "nonexistent_cap")
            self.assertEqual(gaps[0].status, si.GAP_OPEN)

    def test_composable_via_declared_composition(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            for part in ("part_a", "part_b"):
                cg.register_discovered(part, display_name=part, description=part)
                for dim in si.DEFAULT_PROMOTION_POLICY[si.CAP_STATE_DEMONSTRATED]:
                    cg.record_evidence_dimension(part, dim, si.DIM_EVIDENCED)
                gate = si.CapabilityPromotionGate()
                gate.apply_promotion(cg, gate.evaluate(cg.resolve_current(part), si.CAP_STATE_DEMONSTRATED))
            obj = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("combined_cap",), authority_ceiling=("combined_cap",),
            )
            plan, gaps = si.WorkflowCompiler().compile(obj, cg, compositions={"combined_cap": ("part_a", "part_b")})
            self.assertEqual(plan.composable_capability_ids, ("combined_cap",))
            self.assertEqual(plan.missing_capability_ids, ())
            self.assertTrue(plan.is_executable)


class TestCapabilityFoundry(unittest.TestCase):
    def test_successful_probe_reaches_candidate_evidence_but_not_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "cg")
            el = si.EvidenceLedger(tmp / "evid")
            foundry = si.CapabilityFoundry(cg, el)
            gap = si.CapabilityGapRecord(
                gap_id=si._new_id("GAP"), missing_capability_id="new_ability", objective_id=si._new_id("OBJ"),
                smallest_bounded_experiment="run a harmless local probe",
            )
            updated_gap, evidence = foundry.run_probe(gap, lambda: (True, "probe succeeded"), display_name="New Ability", description="d")
            self.assertEqual(updated_gap.status, si.GAP_RESOLVED)
            self.assertIsNotNone(evidence)
            record = cg.resolve_current("new_ability")
            # TOOL CREATED (a probe ran) != CAPABILITY DEMONSTRATED (lifecycle
            # promoted) -- Foundry alone never advances lifecycle_state.
            self.assertEqual(record["lifecycle_state"], si.CAP_STATE_DISCOVERED)
            self.assertEqual(record["evidence_dimensions"]["TECHNICAL"], si.DIM_EVIDENCED)
            self.assertFalse(cg.is_available("new_ability"))

    def test_failed_probe_leaves_gap_open_and_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "cg")
            el = si.EvidenceLedger(tmp / "evid")
            foundry = si.CapabilityFoundry(cg, el)
            gap = si.CapabilityGapRecord(
                gap_id=si._new_id("GAP"), missing_capability_id="failed_ability", objective_id=si._new_id("OBJ"),
                smallest_bounded_experiment="run a harmless local probe",
            )
            updated_gap, evidence = foundry.run_probe(gap, lambda: (False, "probe failed"), display_name="x", description="y")
            self.assertEqual(updated_gap.status, si.GAP_OPEN)
            self.assertIsNone(evidence)
            self.assertEqual(el.list_all(), ())

    def test_promotion_to_demonstrated_requires_separate_gate_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "cg")
            el = si.EvidenceLedger(tmp / "evid")
            foundry = si.CapabilityFoundry(cg, el)
            gap = si.CapabilityGapRecord(
                gap_id=si._new_id("GAP"), missing_capability_id="ability_x", objective_id=si._new_id("OBJ"),
                smallest_bounded_experiment="probe",
            )
            foundry.run_probe(gap, lambda: (True, "ok"), display_name="x", description="y")
            gate = si.CapabilityPromotionGate()
            decision = gate.evaluate(cg.resolve_current("ability_x"), si.CAP_STATE_DEMONSTRATED)
            # TECHNICAL is evidenced (via Foundry) but GOVERNANCE is not yet.
            self.assertEqual(decision.decision, si.NEEDS_MORE_EVIDENCE)
            cg.record_evidence_dimension("ability_x", "GOVERNANCE", si.DIM_EVIDENCED)
            decision2 = gate.evaluate(cg.resolve_current("ability_x"), si.CAP_STATE_DEMONSTRATED)
            self.assertEqual(decision2.decision, si.PROMOTE)
            self.assertFalse(cg.is_available("ability_x"))  # NOT applied yet
            gate.apply_promotion(cg, decision2)
            self.assertTrue(cg.is_available("ability_x"))


class TestCapabilityPromotionGatePolicies(unittest.TestCase):
    def test_reject_when_requested_state_is_not_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("cap", display_name="x", description="y")
            for dim in si.DEFAULT_PROMOTION_POLICY[si.CAP_STATE_DEMONSTRATED]:
                cg.record_evidence_dimension("cap", dim, si.DIM_EVIDENCED)
            gate = si.CapabilityPromotionGate()
            gate.apply_promotion(cg, gate.evaluate(cg.resolve_current("cap"), si.CAP_STATE_DEMONSTRATED))
            decision = gate.evaluate(cg.resolve_current("cap"), si.CAP_STATE_CANDIDATE)  # backward
            self.assertEqual(decision.decision, si.REJECT)

    def test_needs_more_evidence_when_dimension_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("cap", display_name="x", description="y")
            gate = si.CapabilityPromotionGate()
            decision = gate.evaluate(cg.resolve_current("cap"), si.CAP_STATE_DEMONSTRATED)
            self.assertEqual(decision.decision, si.NEEDS_MORE_EVIDENCE)

    def test_configurable_policy_per_capability_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("cap", display_name="x", description="y")
            cg.record_evidence_dimension("cap", "TECHNICAL", si.DIM_EVIDENCED)
            lenient_policy = {si.CAP_STATE_DEMONSTRATED: ("TECHNICAL",)}  # no GOVERNANCE required
            gate = si.CapabilityPromotionGate(policy=lenient_policy, policy_name="lenient_class")
            decision = gate.evaluate(cg.resolve_current("cap"), si.CAP_STATE_DEMONSTRATED)
            self.assertEqual(decision.decision, si.PROMOTE)
            self.assertEqual(decision.policy_name, "lenient_class")

    def test_code_existing_or_a_test_running_is_not_by_itself_promotion(self):
        # A capability with code registered in fabric.CAPABILITIES and no
        # recorded evidence at all must not promote merely by existing.
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("physical_ping", display_name="x", description="y", fabric_capability_id="physical_ping")
            gate = si.CapabilityPromotionGate()
            decision = gate.evaluate(cg.resolve_current("physical_ping"), si.CAP_STATE_DEMONSTRATED)
            self.assertEqual(decision.decision, si.NEEDS_MORE_EVIDENCE)
            self.assertFalse(cg.is_available("physical_ping"))


if __name__ == "__main__":
    unittest.main()
