"""Unit tests for fabric.capabilities.PhysicalPingCapability (MISSION:
FW-PHYSICAL-ANDROID-PC-PAIRING-001) -- the one harmless test capability
the physical device-boundary proof invokes. In-process only; no
network, no filesystem beyond what the existing content_read tests
already exercise via the shared registration import.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric import capabilities as fabric_capabilities  # noqa: F401 -- registers physical_ping


class TestPhysicalPingCapability(unittest.TestCase):
    def setUp(self):
        self.capability = fi.CAPABILITIES["physical_ping"]

    def test_registered_under_expected_capability_id(self):
        self.assertIn("physical_ping", fi.CAPABILITIES)
        self.assertEqual(self.capability.capability_id, "physical_ping")

    def test_echoes_nonce_and_reports_completed(self):
        status, structured_result, error_detail = self.capability.invoke(
            {"artifact_id": "ART-abc", "sha256": "deadbeef"}, b"a-test-nonce"
        )
        self.assertEqual(status, fi.CAP_COMPLETED)
        self.assertIsNone(error_detail)
        self.assertEqual(structured_result["echoed_nonce"], "a-test-nonce")
        self.assertEqual(structured_result["artifact_id"], "ART-abc")
        self.assertEqual(structured_result["evidence_reference"], "deadbeef")
        self.assertIn("responded_at", structured_result)

    def test_non_utf8_payload_fails_honestly(self):
        status, structured_result, error_detail = self.capability.invoke(
            {"artifact_id": "ART-abc", "sha256": "deadbeef"}, b"\xff\xfe not utf-8"
        )
        self.assertEqual(status, fi.CAP_FAILED)
        self.assertIsNone(structured_result)
        self.assertIn("not valid UTF-8", error_detail)

    def test_never_touches_filesystem_or_shell(self):
        # A MOCK-shaped capability's contract: invoke() takes only the
        # manifest dict + bytes already fetched by artifact_handoff, and
        # returns a plain tuple -- no side channel is available for it to
        # reach the filesystem or a shell even if it wanted to.
        import inspect
        source = inspect.getsource(type(self.capability))
        for forbidden in ("subprocess", "os.system", "eval(", "exec(", "open("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
