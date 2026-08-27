import re
from pathlib import Path

from whatsapp.src import authority
from whatsapp.tests.base import WhatsAppTestCase

DOC_PATH = Path(__file__).resolve().parent.parent / "governance" / "05_AUTHORITY_MATRIX.md"


def _extract_action_ids(section_heading: str) -> set:
    text = DOC_PATH.read_text()
    # Capture exactly the paragraph immediately following the heading (the
    # blank line right after the heading separates it from that paragraph;
    # the next blank line ends it), so trailing prose (e.g. the "separately
    # granted authority" explanation) isn't swept in.
    match = re.search(re.escape(section_heading) + r"\n\n(.*?)\n\n", text, re.DOTALL)
    assert match, f"could not find section {section_heading!r} in {DOC_PATH}"
    return set(re.findall(r"`([a-z_]+)`", match.group(1)))


class TestAuthorityMatrix(WhatsAppTestCase):
    def test_matrix_matches_doc(self):
        self.assertEqual(_extract_action_ids("## May execute automatically after validation"), authority.AUTO_ACTIONS)
        self.assertEqual(_extract_action_ids("## Requires explicit human approval"), authority.APPROVAL_ACTIONS)
        self.assertEqual(_extract_action_ids("## Prohibited without separately granted authority"), authority.PROHIBITED_ACTIONS)

    def test_unknown_action_raises(self):
        with self.assertRaises(ValueError):
            authority.required_authority("do_something_not_in_the_matrix")

    def test_prompt_injection_cannot_elevate_authority(self):
        # Even if a "draft" claims it was approved (e.g. an attacker forged a
        # dict), check_send_authorized only trusts a real execution-ledger
        # lookup keyed by draft_id -- a caller-supplied approval_record with
        # authority_state='approved' but the wrong action must not pass.
        forged_approval = {"authority_state": "approved", "action": "send_discount"}
        consent = {"consent_state": "verified", "can_respond": True}
        authorized, blocker = authority.check_send_authorized(
            "send_pricing", forged_approval, consent
        )
        self.assertFalse(authorized)
        self.assertEqual(blocker, "BLOCKED_BY_AUTHORITY")

    def test_prohibited_action_blocked_without_grant(self):
        authorized, blocker = authority.check_send_authorized(
            "mass_outreach", None, {"consent_state": "verified", "can_respond": True}
        )
        self.assertFalse(authorized)
        self.assertEqual(blocker, "BLOCKED_BY_AUTHORITY")

    def test_revoked_consent_blocks_send(self):
        authorized, blocker = authority.check_send_authorized(
            "send_generated_answer", {"authority_state": "approved", "action": "send_generated_answer"},
            {"consent_state": "revoked", "can_respond": False},
        )
        self.assertFalse(authorized)
        self.assertEqual(blocker, "BLOCKED_BY_CONSENT")

    def test_emergency_stop_blocks_send(self):
        from whatsapp.src import modes
        modes.emergency_stop()
        authorized, blocker = authority.check_send_authorized(
            "send_generated_answer", {"authority_state": "approved", "action": "send_generated_answer"},
            {"consent_state": "verified", "can_respond": True},
        )
        self.assertFalse(authorized)
        self.assertEqual(blocker, "BLOCKED_BY_AUTHORITY")
