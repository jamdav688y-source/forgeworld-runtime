"""Differential Cognition / Contradiction Preservation tests (Section 7).

CRITICAL INVARIANT under test: CONSENSUS != TRUTH. Agreement across
perspectives must never cause SynthesisRecord to drop or hide any
perspective's individual claims/assumptions/evidence.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import interface as si


def _objective(**overrides):
    defaults = dict(
        objective_id=si._new_id("OBJ"), desired_state="target reached", current_state="not yet",
        required_capability_ids=("physical_ping",), authority_ceiling=("physical_ping",),
    )
    defaults.update(overrides)
    return si.ObjectiveContract(**defaults)


class TestDifferentialCognitionEngine(unittest.TestCase):
    def test_default_five_perspectives_are_configurable_not_hardwired(self):
        engine = si.DifferentialCognitionEngine()
        self.assertEqual(set(engine.perspectives), {
            si.PERSPECTIVE_PRIMARY, si.PERSPECTIVE_ADVERSARIAL, si.PERSPECTIVE_ALTERNATIVE,
            si.PERSPECTIVE_COMMERCIAL, si.PERSPECTIVE_GOVERNANCE,
        })
        custom = si.DifferentialCognitionEngine(perspectives={"ONLY_ONE": si.primary_perspective})
        records, cmap, synth = custom.run(_objective())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].perspective_id, "ONLY_ONE")

    def test_perspectives_never_call_a_model_are_pure_deterministic_functions(self):
        obj = _objective()
        records1, _, _ = si.DifferentialCognitionEngine().run(obj)
        records2, _, _ = si.DifferentialCognitionEngine().run(obj)
        # Same objective -> same (non-timestamp) content every time: no
        # model call, no randomness, no hidden network dependency.
        self.assertEqual(
            [(r.perspective_id, r.claims, r.assumptions, r.proposed_actions) for r in records1],
            [(r.perspective_id, r.claims, r.assumptions, r.proposed_actions) for r in records2],
        )

    def test_disagreement_is_preserved_not_voted_away(self):
        obj = _objective()  # ALTERNATIVE always dissents with a different proposed action
        records, cmap, synth = si.DifferentialCognitionEngine().run(obj)
        self.assertIn("explore_alternative_composition", cmap.disagreement)
        self.assertEqual(synth.preserved_disagreement, cmap.disagreement)
        self.assertNotEqual(synth.preserved_disagreement, ())

    def test_synthesis_never_drops_a_perspectives_record_even_under_full_agreement(self):
        # Force full agreement across every perspective, so agreement ==
        # every action and disagreement == (). Even then, every perspective's
        # own record must still be individually traceable via
        # perspective_record_ids -- consensus must not erase who said what.
        def unanimous(objective, evidence, constraints):
            return {"claims": ("agreed",), "assumptions": (), "evidence_used": (), "uncertainties": (), "proposed_actions": ("go",)}

        engine = si.DifferentialCognitionEngine(perspectives={"A": unanimous, "B": unanimous, "C": unanimous})
        records, cmap, synth = engine.run(_objective())
        self.assertEqual(cmap.disagreement, ())
        self.assertEqual(cmap.agreement, ("go",))
        # Consensus reached, but nothing about WHO reached it was discarded.
        self.assertEqual(len(cmap.perspective_record_ids), 3)
        self.assertEqual(set(synth.perspective_record_ids), {r.record_id for r in records})

    def test_missing_evidence_drives_the_recommended_next_step(self):
        obj = _objective(evidence_required=("customer_confirmed_problem",))
        records, cmap, synth = si.DifferentialCognitionEngine().run(obj)
        self.assertIn("customer_confirmed_problem", cmap.missing_evidence)
        self.assertIn("gather missing evidence", synth.recommended_next_step)

    def test_no_authority_ceiling_surfaces_as_governance_uncertainty_not_silently_ignored(self):
        obj = _objective(authority_ceiling=())
        records, cmap, synth = si.DifferentialCognitionEngine().run(obj)
        gov_record = next(r for r in records if r.perspective_id == si.PERSPECTIVE_GOVERNANCE)
        self.assertTrue(any("authority_ceiling" in u for u in gov_record.uncertainties))
        self.assertIn("declare_authority_ceiling_before_executing", cmap.disagreement + cmap.agreement)


if __name__ == "__main__":
    unittest.main()
