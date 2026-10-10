"""ReachabilityEngine tests (Section 16), including restart attribution
(Section 30: a ReachabilityDelta must remain attributable to the
CapabilityGraph version that produced it)."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import interface as si


def _promote(cg, capability_id, state=si.CAP_STATE_DEMONSTRATED):
    if cg.resolve_current(capability_id) is None:
        cg.register_discovered(capability_id, display_name=capability_id, description=capability_id)
    for dim in si.DEFAULT_PROMOTION_POLICY[state]:
        cg.record_evidence_dimension(capability_id, dim, si.DIM_EVIDENCED)
    gate = si.CapabilityPromotionGate()
    gate.apply_promotion(cg, gate.evaluate(cg.resolve_current(capability_id), state))


class TestReachabilityEngine(unittest.TestCase):
    def test_new_capability_makes_previously_unreachable_class_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            _promote(cg, "cap_a")
            objective_classes = {"CLASS_ONE": ("cap_a", "cap_b")}
            engine = si.ReachabilityEngine(cg, objective_classes)
            before = frozenset(engine._currently_satisfied_classes())
            self.assertEqual(before, frozenset())  # cap_b missing -> not yet reachable

            _promote(cg, "cap_b")
            delta = engine.compute_delta_after_promotion("cap_b", before)
            self.assertIn("CLASS_ONE", delta.newly_reachable_objective_classes)
            self.assertEqual(delta.dependency_basis["CLASS_ONE"], ("cap_a", "cap_b"))

    def test_already_reachable_class_is_not_reported_as_newly_reachable_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            _promote(cg, "cap_a")
            objective_classes = {"CLASS_ONE": ("cap_a",)}
            engine = si.ReachabilityEngine(cg, objective_classes)
            already_satisfied = frozenset(engine._currently_satisfied_classes())
            self.assertEqual(already_satisfied, frozenset({"CLASS_ONE"}))

            _promote(cg, "cap_unrelated")
            delta = engine.compute_delta_after_promotion("cap_unrelated", already_satisfied)
            self.assertEqual(delta.newly_reachable_objective_classes, ())

    def test_objective_arrival_reports_relevant_known_capabilities_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            cg.register_discovered("known_cap", display_name="x", description="y")
            engine = si.ReachabilityEngine(cg, {})
            obj = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("known_cap", "totally_unknown_cap"),
            )
            delta = engine.compute_relevant_capabilities_for_objective(obj)
            self.assertEqual(delta.newly_relevant_capabilities, ("known_cap",))
            self.assertEqual(delta.trigger, "objective_arrived")

    def test_delta_is_attributable_to_the_capability_graph_version_that_produced_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp)
            _promote(cg, "cap_a")
            engine = si.ReachabilityEngine(cg, {"CLASS_ONE": ("cap_a",)})
            delta = engine.compute_delta_after_promotion("cap_a", frozenset())
            version_at_delta_time = cg.version()
            self.assertEqual(delta.capability_graph_version, version_at_delta_time)

            # Restart: fresh CapabilityGraph object over the same directory.
            cg2 = si.CapabilityGraph(tmp)
            self.assertEqual(cg2.version(), version_at_delta_time)
            self.assertEqual(delta.capability_graph_version, cg2.version())

    def test_uncertainty_field_documents_deterministic_reasoning_no_model_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))
            engine = si.ReachabilityEngine(cg, {})
            delta = engine.compute_delta_after_promotion("anything", frozenset())
            self.assertIn("deterministic", delta.uncertainty)


if __name__ == "__main__":
    unittest.main()
