import unittest

from router.architecture_router import MissionArchitectureContext, assess_architecture


class ArchitectureRouterTests(unittest.TestCase):
    def test_chatbot_is_minimum_for_plain_conversation(self):
        result = assess_architecture(MissionArchitectureContext())
        self.assertEqual(result["required_level"], 1)
        self.assertEqual(result["status"], "authorized")

    def test_grounded_answers_require_rag(self):
        result = assess_architecture(
            MissionArchitectureContext(grounding_required=True, evidence_level="hypothesis")
        )
        self.assertEqual(result["required_architecture"], "rag_application")
        self.assertTrue(result["execution_authorized"])

    def test_tools_require_single_agent(self):
        result = assess_architecture(
            MissionArchitectureContext(tool_actions=True, evidence_level="prototype")
        )
        self.assertEqual(result["required_architecture"], "single_agent")

    def test_parallel_roles_require_multi_agent(self):
        result = assess_architecture(
            MissionArchitectureContext(
                parallel_specialists=True,
                evidence_level="validated",
            )
        )
        self.assertEqual(result["required_architecture"], "multi_agent_system")

    def test_autonomy_is_evidence_blocked(self):
        result = assess_architecture(
            MissionArchitectureContext(
                event_triggered=True,
                self_correction=True,
                evidence_level="prototype",
                controls=["validation", "recovery"],
            )
        )
        self.assertEqual(result["status"], "evidence_blocked")
        self.assertEqual(result["authorized_architecture"], "single_agent")

    def test_consequential_action_requires_human_approval(self):
        result = assess_architecture(
            MissionArchitectureContext(
                tool_actions=True,
                consequential_actions=True,
                evidence_level="prototype",
            )
        )
        self.assertEqual(result["status"], "control_blocked")
        self.assertIn("human_approval", result["missing_controls"])

    def test_enterprise_requires_full_governance_controls(self):
        result = assess_architecture(
            MissionArchitectureContext(
                enterprise_scale=True,
                evidence_level="operational",
                controls=["validation", "recovery"],
            )
        )
        self.assertEqual(result["required_level"], 6)
        self.assertEqual(result["status"], "control_blocked")
        self.assertIn("observability", result["missing_controls"])

    def test_detects_unnecessary_architecture(self):
        result = assess_architecture(
            MissionArchitectureContext(requested_level=4, evidence_level="validated")
        )
        self.assertEqual(result["requested_fit"], "over_complex")


if __name__ == "__main__":
    unittest.main()
