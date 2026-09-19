"""Tests for the forgeworld_mobile_research capability registration.

Written against Python's stdlib `unittest`, not pytest: this environment
has no pytest installed, and installing anything is out of scope for
this change. test_discover.py (pytest-based) is untouched by this file
and this file does not depend on it.

Every test that exercises router.route() patches discover.probe_all,
discover.write_state, and mission_router.DECISIONS_PATH so that running
these tests never writes to the real capabilities/state.json or
router/decisions.jsonl -- those are live operational files, not test
fixtures.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CAPABILITIES_DIR = Path(__file__).resolve().parent.parent
ROUTER_DIR = CAPABILITIES_DIR.parent / "router"
sys.path.insert(0, str(CAPABILITIES_DIR))
sys.path.insert(0, str(ROUTER_DIR))

import discover  # noqa: E402
import mission_router  # noqa: E402

CAP_ID = "forgeworld_mobile_research"


def _load_capability():
    matches = [c for c in discover.load_registry() if c["id"] == CAP_ID]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {CAP_ID!r} entry, found {len(matches)}")
    return matches[0]


class TestRegistryLoadsCapability(unittest.TestCase):
    """1. the registry loads the capability."""

    def test_capability_present_with_required_contract_fields(self):
        cap = _load_capability()
        for field in (
            "id", "kind", "provider", "purpose", "inputs", "outputs",
            "check", "tags", "cost", "locality", "dependencies",
            "external_effects", "failure_state", "evidence_provenance",
            "validation_state",
        ):
            self.assertIn(field, cap, f"missing contract field: {field}")

    def test_cost_has_all_axes_router_requires(self):
        cap = _load_capability()
        for axis in mission_router.COST_AXES:
            self.assertIn(axis, cap["cost"])

    def test_locality_and_provider_agree_it_is_local(self):
        cap = _load_capability()
        self.assertEqual(cap["provider"], "local")
        self.assertEqual(cap["locality"], "local_only")

    def test_evidence_provenance_disclaims_lead_customer_commercial_status(self):
        cap = _load_capability()
        text = cap["evidence_provenance"].lower()
        self.assertIn("lead", text)
        self.assertIn("commercial", text)
        self.assertIn("never", text)

    def test_validation_state_does_not_claim_device_validated(self):
        cap = _load_capability()
        self.assertTrue(cap["validation_state"]["registered"])
        self.assertFalse(cap["validation_state"]["device_validated"])


class TestDiscoveryReachability(unittest.TestCase):
    """2. discovery can determine its actual reachability."""

    def test_real_probe_in_this_environment_is_honest(self):
        # tesseract is not installed in this sandbox; the probe must say
        # so plainly rather than reporting false reachability.
        cap = _load_capability()
        confidence, evidence, level = discover.probe_one(cap["check"])
        self.assertEqual(confidence, 0.0)
        self.assertEqual(level, "UNREACHABLE")
        self.assertIn("tesseract", evidence)

    def test_probe_recognizes_a_present_and_correctly_identifying_tool(self):
        # Proves the probe *can* report reachable=True, without installing
        # real tesseract: a fake executable stands in for it.
        import stat
        cap = _load_capability()
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "tesseract"
            fake.write_text("#!/bin/sh\necho 'tesseract 5.3.0'\nexit 0\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            confidence, level, evidence = discover._probe_resolved(str(fake), cap["check"]["verify"])
        self.assertEqual(confidence, 1.0)
        self.assertIn(level, ("IDENTITY_VERIFIED", "VERSION_VERIFIED"))

    def test_probe_all_includes_capability_with_honest_evidence_level(self):
        state = discover.probe_all()
        self.assertIn(CAP_ID, state)
        self.assertIn("evidence_level", state[CAP_ID])  # command check
        self.assertIsInstance(state[CAP_ID]["reachability_confidence"], float)


class TestRouterVisibility(unittest.TestCase):
    """3. the router can see it for appropriate capture/intake work."""

    def test_scored_for_customer_capture_tags(self):
        cap = _load_capability()
        reachability_state = {CAP_ID: {"reachability_confidence": 1.0, "evidence": "forced reachable for test"}}
        scored = mission_router.score_capability(
            cap, required_tags=["customer_capture"], reachability_state=reachability_state, history=[]
        )
        self.assertTrue(scored["reachable"])
        self.assertGreater(scored["confidence"]["task_fit"], 0.0)

    def test_router_selects_it_when_reachable_and_tags_match(self):
        registry = discover.load_registry()
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(mission_router.discover, "probe_all") as fake_probe, \
             mock.patch.object(mission_router.discover, "write_state"), \
             mock.patch.object(mission_router, "DECISIONS_PATH", Path(d) / "decisions.jsonl"):
            fake_probe.return_value = {
                c["id"]: {
                    "reachability_confidence": 1.0 if c["id"] == CAP_ID else 0.0,
                    "evidence": "forced for test",
                }
                for c in registry
            }
            decision = mission_router.route(
                objective="Ingest new phone screenshots",
                required_tags=["screenshot_ingestion"],
                mission_id="TEST-CAPTURE-ROUTING",
            )
        self.assertEqual(decision["selected_capability"], CAP_ID)


class TestUnreachableFailsHonestly(unittest.TestCase):
    """4. unreachable dependencies fail honestly."""

    def test_scoring_marks_it_unreachable_when_probe_says_so(self):
        cap = _load_capability()
        reachability_state = {CAP_ID: {"reachability_confidence": 0.0, "evidence": "tesseract not found"}}
        scored = mission_router.score_capability(
            cap, required_tags=["customer_capture"], reachability_state=reachability_state, history=[]
        )
        self.assertFalse(scored["reachable"])

    def test_route_queues_rather_than_silently_substituting(self):
        registry = discover.load_registry()
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(mission_router.discover, "probe_all") as fake_probe, \
             mock.patch.object(mission_router.discover, "write_state"), \
             mock.patch.object(mission_router, "DECISIONS_PATH", Path(d) / "decisions.jsonl"):
            fake_probe.return_value = {
                c["id"]: {"reachability_confidence": 0.0, "evidence": "forced unreachable for test"}
                for c in registry
            }
            decision = mission_router.route(
                objective="Ingest new phone screenshots (all capabilities down)",
                required_tags=["screenshot_ingestion"],
                mission_id="TEST-CAPTURE-QUEUED",
            )
        self.assertEqual(decision["status"], "queued_no_reachable_capability")
        self.assertIsNone(decision["selected_capability"])


class TestExistingRoutingDoesNotRegress(unittest.TestCase):
    """5. existing routing behavior does not regress."""

    def test_registry_still_has_original_eleven_capabilities_unchanged(self):
        caps = {c["id"]: c for c in discover.load_registry()}
        self.assertEqual(len(caps), 12)  # 11 original + this one
        self.assertEqual(caps["python"]["check"]["value"], "python3")
        self.assertEqual(
            caps["python"]["tags"],
            ["scripting", "data_processing", "automation", "analysis"],
        )
        self.assertEqual(caps["git"]["check"], {"type": "command", "value": "git"})

    def test_python_still_wins_for_scripting_tag(self):
        registry = discover.load_registry()
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(mission_router.discover, "probe_all") as fake_probe, \
             mock.patch.object(mission_router.discover, "write_state"), \
             mock.patch.object(mission_router, "DECISIONS_PATH", Path(d) / "decisions.jsonl"):
            fake_probe.return_value = {
                c["id"]: {
                    "reachability_confidence": 1.0 if c["id"] in ("python", "git") else 0.0,
                    "evidence": "forced for test",
                }
                for c in registry
            }
            decision = mission_router.route(
                objective="Run a scripting task",
                required_tags=["scripting"],
                mission_id="TEST-REGRESSION-SCRIPTING",
            )
        self.assertEqual(decision["selected_capability"], "python")


if __name__ == "__main__":
    unittest.main()
