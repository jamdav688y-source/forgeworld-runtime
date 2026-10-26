import json

from whatsapp.src import classify, draft, ledger, normalize
from whatsapp.tests.base import WhatsAppTestCase, load_fixture


class TestDraft(WhatsAppTestCase):
    def _classified_event(self, fixture_name):
        payload = json.loads(load_fixture(fixture_name))
        text = payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]
        event = normalize.extract_events(payload, "0" * 64, True)[0]
        return event, classify.classify(event, text)

    def test_draft_is_never_pre_approved(self):
        event, classification = self._classified_event("webhook_valid_text.json")
        result = draft.compile_draft(event, classification)
        self.assertEqual(result["authority_state"], "draft")
        self.assertEqual(result["terminal_state"], "READY_FOR_HUMAN_APPROVAL")

    def test_pricing_draft_avoids_stating_a_price(self):
        event, classification = self._classified_event("webhook_valid_text.json")
        result = draft.compile_draft(event, classification)
        self.assertNotRegex(result["message"], r"\$\d")
        self.assertIn(
            "did not state a specific price without human approval",
            result["reasoning"]["prohibited_commitments_avoided"],
        )

    def test_draft_writes_ready_for_approval_to_execution_ledger(self):
        event, classification = self._classified_event("webhook_valid_text.json")
        result = draft.compile_draft(event, classification)
        entries = ledger.find(ledger.EXECUTION_LEDGER, draft_id=result["draft_id"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["state"], "READY_FOR_HUMAN_APPROVAL")

    def test_injected_instruction_does_not_change_required_authority_tier(self):
        event, classification = self._classified_event("webhook_prompt_injection.json")
        result = draft.compile_draft(event, classification)
        self.assertNotEqual(result["required_authority_tier"], "auto")
        self.assertIn(result["required_authority_tier"], {"approval"})
