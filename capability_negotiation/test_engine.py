"""Real tests for the Capability Negotiation Engine -- run with:
  python3 -m pytest capability_negotiation/test_engine.py -v
(or plain `python3 capability_negotiation/test_engine.py` -- see __main__ runner below,
since this environment's system Python doesn't have pytest installed by default
and the engine has no other dependency that would require a venv.)
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
from states import (
    AVAILABLE, UNAVAILABLE, UNKNOWN, OPERATOR_REQUIRED, DISCOVERED_AFTER_STARTUP,
    BLOCKED_BY_POLICY, BLOCKED_BY_PLATFORM, DELEGATE_TO_WINDOWS,
    RESUME_READY, RESUME_STILL_BLOCKED, RESUME_NO_PRIOR_GAP,
)


class CapabilityNegotiationEngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.out_dir = Path(self._tmp) / "report"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        os.environ.pop("OPENAI_API_KEY", None)

    def test_windows_mission_is_blocked_on_this_linux_container(self):
        result = engine.negotiate("windows_desktop_deployment")
        self.assertFalse(result.can_proceed)
        states = {r.capability_id: r.state for r in result.requirements}
        self.assertEqual(states["windows_filesystem_execution"], BLOCKED_BY_PLATFORM)
        self.assertEqual(states["windows_shell_execution"], BLOCKED_BY_PLATFORM)
        self.assertEqual(states["remote_desktop_access"], OPERATOR_REQUIRED)

    def test_android_mission_is_honest_about_running_on_neither_phone_nor_windows(self):
        result = engine.negotiate("android_mobile_deployment")
        self.assertFalse(result.can_proceed)
        states = {r.capability_id: r.state for r in result.requirements}
        # this container is neither a phone nor Windows -- Termux-only
        # capabilities must read UNAVAILABLE, never a guessed AVAILABLE
        self.assertEqual(states["android_filesystem_access"], UNAVAILABLE)
        self.assertEqual(states["termux_shell_execution"], UNAVAILABLE)
        # these ARE real, working software in this repo -- self-checks
        self.assertEqual(states["screenshot_ingestion"], AVAILABLE)
        self.assertEqual(states["local_research_index"], AVAILABLE)
        self.assertEqual(states["cinema_review"], AVAILABLE)
        # manual/operator-gated capabilities must never be guessed either way
        self.assertEqual(states["camera_capture"], UNKNOWN)
        self.assertEqual(states["connector_authentication"], UNKNOWN)

    def test_delegated_capabilities_do_not_block_the_mobile_mission(self):
        result = engine.negotiate("android_mobile_deployment")
        states = {r.capability_id: r.state for r in result.requirements}
        self.assertEqual(states["desktop_shortcut_creation"], DELEGATE_TO_WINDOWS)
        self.assertEqual(states["cinema_render_1080p_24fps"], DELEGATE_TO_WINDOWS)
        gap_ids = {g.capability_id for g in result.gaps}
        self.assertNotIn("desktop_shortcut_creation", gap_ids)
        self.assertNotIn("cinema_render_1080p_24fps", gap_ids)

    def test_termux_probe_is_not_fooled_by_platform_system_reporting_linux(self):
        # Termux's own Python reports platform.system() == 'Linux', same as
        # this container -- the termux check type must use TERMUX_VERSION/
        # PREFIX, not platform.system(), or it could never tell them apart
        # in either direction. Confirm the two checks are actually distinct.
        import discover
        platform_result = discover.probe_one({"type": "platform", "value": "Linux"})
        termux_result = discover.probe_one({"type": "termux", "value": None})
        self.assertEqual(platform_result[0], 1.0)  # this really is Linux
        self.assertEqual(termux_result[0], 0.0)    # but it is not Termux

    def test_windows_gap_evidence_is_specific_not_generic_failed(self):
        result = engine.negotiate("windows_desktop_deployment")
        for gap in result.gaps:
            self.assertNotEqual(gap.evidence.strip().lower(), "failed")
            self.assertTrue(len(gap.evidence) > 10)
            self.assertIsNotNone(gap.resolution_action)

    def test_satisfiable_mission_reports_available(self):
        result = engine.negotiate("cinema_release_commit")
        self.assertTrue(result.can_proceed)
        self.assertEqual(result.gaps, [])
        for r in result.requirements:
            self.assertEqual(r.state, AVAILABLE)

    def test_connector_mission_without_live_evidence_is_operator_required_not_a_guess(self):
        result = engine.negotiate("third_party_notification_workflow")
        self.assertFalse(result.can_proceed)
        for r in result.requirements:
            self.assertEqual(r.state, OPERATOR_REQUIRED)

    def test_connector_mission_with_real_live_evidence_resolves_available(self):
        result = engine.negotiate("third_party_notification_workflow", live_connectors=["Slack", "Gmail"])
        self.assertTrue(result.can_proceed)
        for r in result.requirements:
            self.assertEqual(r.state, AVAILABLE)

    def test_connector_mission_with_evidence_of_absence_is_unavailable(self):
        result = engine.negotiate("third_party_notification_workflow", live_connectors=["Airtable"])
        states = {r.capability_id: r.state for r in result.requirements}
        self.assertEqual(states["slack"], UNAVAILABLE)
        self.assertEqual(states["gmail"], UNAVAILABLE)

    def test_policy_override_can_only_block_never_force_available(self):
        result = engine.negotiate("cinema_release_commit", policy_overrides={"git": "test: blocked for this test"})
        states = {r.capability_id: r.state for r in result.requirements}
        self.assertEqual(states["git"], BLOCKED_BY_POLICY)
        self.assertFalse(result.can_proceed)

    def test_publish_report_writes_all_five_required_files(self):
        result = engine.negotiate("cinema_release_commit")
        out_dir = engine.publish_report(result, out_dir=self.out_dir)
        for fname in ["CAPABILITY_REGISTRY.json", "CAPABILITY_REPORT.json", "CAPABILITY_GAPS.json",
                      "OPERATOR_ACTIONS.md", "CAPABILITY_EVIDENCE.json"]:
            self.assertTrue((out_dir / fname).exists(), f"missing {fname}")

    def test_operator_actions_md_is_empty_of_actions_when_ready(self):
        result = engine.negotiate("cinema_release_commit")
        md = engine.generate_operator_actions_md(result)
        self.assertIn("READY", md)
        self.assertIn("No operator action required", md)

    def test_operator_actions_md_lists_every_gap_when_blocked(self):
        result = engine.negotiate("windows_desktop_deployment")
        md = engine.generate_operator_actions_md(result)
        self.assertIn("BLOCKED", md)
        for gap in result.gaps:
            self.assertIn(gap.capability_id, md)

    def test_resume_detects_newly_available_capability(self):
        os.environ.pop("OPENAI_API_KEY", None)
        result = engine.negotiate("capability_negotiation_selftest")
        engine.publish_report(result, out_dir=self.out_dir)
        self.assertFalse(result.can_proceed)

        os.environ["OPENAI_API_KEY"] = "test-value"
        outcome = engine.check_resume("capability_negotiation_selftest", out_dir=self.out_dir)
        self.assertIn("chatgpt", outcome["newly_resolved"])
        self.assertTrue(outcome["can_proceed_now"])
        self.assertEqual(outcome["overall_status"], RESUME_READY)

    def test_resume_is_a_noop_when_nothing_changed(self):
        result = engine.negotiate("windows_desktop_deployment")
        engine.publish_report(result, out_dir=self.out_dir)
        outcome = engine.check_resume("windows_desktop_deployment", out_dir=self.out_dir)
        self.assertEqual(outcome["newly_resolved"], [])
        self.assertFalse(outcome["can_proceed_now"])
        self.assertEqual(outcome["overall_status"], RESUME_STILL_BLOCKED)

    def test_resume_with_no_prior_report_is_labeled_no_prior_gap(self):
        outcome = engine.check_resume("cinema_release_commit", out_dir=self.out_dir)
        self.assertEqual(outcome["overall_status"], RESUME_NO_PRIOR_GAP)

    def test_unknown_mission_raises(self):
        with self.assertRaises(KeyError):
            engine.negotiate("not_a_real_mission")

    def test_unregistered_capability_id_does_not_crash(self):
        # A mission requiring a capability id that isn't in the registry
        # should surface as a clear gap, not an unhandled exception.
        from missions import MISSIONS
        MISSIONS["_test_bad_mission"] = {
            "objective": "test", "required_capability_ids": ["totally_made_up_capability_xyz"],
        }
        try:
            result = engine.negotiate("_test_bad_mission")
            self.assertFalse(result.can_proceed)
            self.assertIn("not a registered capability", result.gaps[0].evidence)
        finally:
            del MISSIONS["_test_bad_mission"]


if __name__ == "__main__":
    unittest.main()
