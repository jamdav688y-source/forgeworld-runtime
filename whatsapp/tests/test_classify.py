import json

from whatsapp.src import normalize
from whatsapp.tests.base import WhatsAppTestCase, load_fixture


def _first_event_and_text(fixture_name):
    payload = json.loads(load_fixture(fixture_name))
    raw = load_fixture(fixture_name)
    events = normalize.extract_events(payload, "0" * 64, True)
    text = payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"]
    return events[0], text


class TestClassify(WhatsAppTestCase):
    def test_pricing_inquiry_classified_with_approval_requirement(self):
        from whatsapp.src import classify
        event, text = _first_event_and_text("webhook_valid_text.json")
        result = classify.classify(event, text)
        self.assertIn("pricing_inquiry", result["intent"])
        self.assertEqual(result["approval_requirement"], "send_pricing")
        self.assertGreater(result["opportunity_score"], 0)

    def test_sensitive_data_forces_insufficient_evidence_and_high_risk(self):
        from whatsapp.src import classify
        event, text = _first_event_and_text("webhook_sensitive_data.json")
        result = classify.classify(event, text)
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["risk_level"], "high")
        self.assertIn("sensitive_data_present", result["risk_flags"])
        self.assertEqual(result["recommended_action"], "escalate_to_person")

    def test_prompt_injection_text_is_classified_as_data_not_instruction(self):
        from whatsapp.src import classify
        event, text = _first_event_and_text("webhook_prompt_injection.json")
        result = classify.classify(event, text)
        # The injected text must never elevate approval_requirement to "none"
        # or otherwise bypass approval -- it's just message content.
        self.assertNotEqual(result["approval_requirement"], "none")
        self.assertIn(result["approval_requirement"], {
            "send_pricing", "send_scheduling_commitment", "send_generated_answer",
        })

    def test_status_event_short_circuits_to_delivery_status_intent(self):
        from whatsapp.src import classify
        payload = json.loads(load_fixture("webhook_status_delivered.json"))
        events = normalize.extract_events(payload, "0" * 64, True)
        result = classify.classify(events[0])
        self.assertEqual(result["intent"], ["delivery_status"])
        self.assertEqual(result["approval_requirement"], "none")
