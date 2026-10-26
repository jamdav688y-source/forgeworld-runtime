"""Lens v2 presentation tests: viewer-facing separation over existing lens
outputs, with no change to any lens record, label or provenance."""
import unittest

from cognition import cxp, presentation as pv
from cognition import production as pr
from cognition.tests.test_production import ProductionTestCase


class TestClassification(unittest.TestCase):
    def test_methodology_notes_are_recognised(self):
        for note in ("a commit message states intent; the code it changed was not inspected by this lens",
                     "audience comprehension is estimated from a word list, not tested with viewers",
                     "dramatization: every scene must be checked against evidence before production"):
            self.assertTrue(pv.is_methodology_note(note), note)
        for uncertainty in ("the claim rests on a single origin", "no controlled experiment is referenced"):
            self.assertFalse(pv.is_methodology_note(uncertainty), uncertainty)

    def test_question_table_is_fixed_and_process_questions_are_internal(self):
        self.assertEqual(set(pv.QUESTION_PRESENTATION), set(cxp.LENS_QUESTIONS))
        self.assertEqual(pv.QUESTION_PRESENTATION[cxp.Q_READY_FOR_EPISODE][1], pv.INTERNAL_ONLY)
        self.assertEqual(pv.QUESTION_PRESENTATION[cxp.Q_CLAIM_ESTABLISHED][1], pv.VIEWER)

    def test_verification_guard_ignores_negations(self):
        self.assertFalse(pr.asserts_verification("no input is verified; the claim is so far a description"))
        self.assertFalse(pr.asserts_verification("This is not proven yet"))
        self.assertTrue(pr.asserts_verification("It is a proven fact that the grant was refused"))
        self.assertTrue(pr.asserts_verification("Confirmed by tests."))


class TestPackagePresentation(ProductionTestCase):
    def setUp(self):
        super().setUp()
        self.before = {m["record_id"]: m for m in self.x.all_record_metadata()}
        self.package = self.build()["package"]
        self.pres = self.package["presentation"]

    def test_lens_records_are_untouched(self):
        after = {m["record_id"]: m for m in self.x.all_record_metadata() if m["kind"] != cxp.KIND_PRODUCTION_PACKAGE}
        self.assertEqual(after, self.before)

    def test_viewer_questions_carry_no_methodology_notes(self):
        questions = [q["question"] for q in self.package["future_intake_questions"]]
        self.assertTrue(questions)
        for q in questions:
            self.assertFalse(pv.is_methodology_note(q), q)
            self.assertTrue(q.endswith("?"), q)
        self.assertIn(self.x.get_record(self.question).payload()["statement"], questions)

    def test_everything_is_still_disclosed(self):
        c = self.x.get_record(self.candidate).payload()
        self.assertEqual(sorted(self.pres["methodology_notes"] + self.pres["uncertainty_disclosures"]), sorted(c["open_questions"]))
        self.assertEqual(sorted(self.pres["claims_requiring_disclosure"] + self.pres["audience_questions_asked"]),
                         sorted(c["unsupported_claims"]))
        self.assertEqual(self.package["disclosures"]["open_questions"], c["open_questions"])
        self.assertEqual({d["claim"] for d in self.package["disclosures"]["unsupported_claims"]}, set(c["unsupported_claims"]))

    def test_audience_question_is_not_presented_as_a_claim(self):
        statement = self.x.get_record(self.question).payload()["statement"]
        self.assertEqual(self.pres["audience_questions_asked"], [statement])
        label = next(d["label"] for d in self.package["disclosures"]["unsupported_claims"] if d["claim"] == statement)
        self.assertTrue(label.startswith("AUDIENCE QUESTION"))

    def test_process_contradictions_are_flagged_internal(self):
        internal = [s for s in self.package["scenes"] if s["audience"] == pv.INTERNAL_ONLY]
        self.assertEqual(len(internal), 1)
        self.assertEqual(internal[0]["on_screen_text"], "Not for broadcast")
        self.assertEqual({c["audience"] for c in self.pres["contradiction_disclosures"]}, {pv.INTERNAL_ONLY})
        self.assertIn("Production notes (methodology, not for broadcast)", self.builder.load(self.build()["package_id"])["markdown"])


if __name__ == "__main__":
    unittest.main()
