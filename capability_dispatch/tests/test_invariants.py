"""Regression tests for the ForgeWorld capability-design invariants."""
import unittest

from governance.invariants import (
    evaluate_capability_design_invariants,
    invariants_permit_execution,
)
from governance.types import AuthorityState, EvidenceState


class CapabilityDesignInvariantTests(unittest.TestCase):
    def evaluate(self, **overrides):
        values = {
            "capability_available": True,
            "disposition": "SANDBOX_PROBE",
            "authority_state": AuthorityState.ALLOWED_BOUNDED,
            "supporting_evidence_state": EvidenceState.SUPPORTED,
            "derived_evidence_state": EvidenceState.SUPPORTED,
            "evidence_references": ["EVD-001"],
        }
        values.update(overrides)
        return evaluate_capability_design_invariants(**values)

    def state(self, results, invariant_id):
        return next(r["state"] for r in results if r["invariant_id"] == invariant_id)

    def test_valid_bounded_execution_satisfies_runtime_invariants(self):
        results = self.evaluate()
        self.assertTrue(invariants_permit_execution(results))
        self.assertEqual(self.state(results, "FW-INV-CAPABILITY-001"), "SATISFIED")
        self.assertEqual(self.state(results, "FW-INV-AUTHORITY-002"), "SATISFIED")
        self.assertEqual(self.state(results, "FW-INV-EVIDENCE-003"), "SATISFIED")

    def test_capability_never_implies_authority(self):
        results = self.evaluate(authority_state=AuthorityState.HUMAN_ONLY)
        self.assertFalse(invariants_permit_execution(results))
        self.assertEqual(self.state(results, "FW-INV-AUTHORITY-002"), "VIOLATED")

    def test_unknown_authority_fails_closed(self):
        results = self.evaluate(authority_state="NOT_A_STATE")
        self.assertFalse(invariants_permit_execution(results))
        self.assertEqual(self.state(results, "FW-INV-AUTHORITY-002"), "UNRESOLVED")

    def test_evidence_strength_cannot_inflate(self):
        results = self.evaluate(
            supporting_evidence_state=EvidenceState.OBSERVED,
            derived_evidence_state=EvidenceState.VALIDATED,
        )
        self.assertFalse(invariants_permit_execution(results))
        self.assertEqual(self.state(results, "FW-INV-EVIDENCE-003"), "VIOLATED")

    def test_success_does_not_self_promote(self):
        results = self.evaluate(
            disposition="OBSERVE",
            execution_succeeded=True,
            promotion_requested=True,
            promotion_authorized=False,
        )
        self.assertFalse(invariants_permit_execution(results))
        self.assertEqual(self.state(results, "FW-INV-PROMOTION-004"), "VIOLATED")

    def test_independently_authorized_promotion_is_satisfied(self):
        results = self.evaluate(
            disposition="OBSERVE",
            execution_succeeded=True,
            promotion_requested=True,
            promotion_authorized=True,
        )
        self.assertTrue(invariants_permit_execution(results))
        self.assertEqual(self.state(results, "FW-INV-PROMOTION-004"), "SATISFIED")

    def test_nonexecuting_disposition_consumes_no_authority(self):
        results = self.evaluate(disposition="BLOCK", authority_state=AuthorityState.DENIED)
        self.assertEqual(self.state(results, "FW-INV-AUTHORITY-002"), "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
