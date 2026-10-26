import json

from whatsapp.src import ledger, webhook_adapter
from whatsapp.tests.base import TEST_APP_SECRET, WhatsAppTestCase, load_fixture, sign


class TestWebhookAdapter(WhatsAppTestCase):
    def test_valid_webhook_is_accepted_and_ledgered(self):
        raw = load_fixture("webhook_valid_text.json")
        result = webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(result["status"], "SAFE_AUTOMATION_EXECUTED")
        self.assertEqual(len(result["events"]), 1)
        ledgered = ledger.read_all(ledger.CONVERSATION_LEDGER)
        self.assertEqual(len(ledgered), 1)
        self.assertTrue(ledgered[0]["provenance"]["webhook_verified"])

    def test_invalid_signature_is_blocked_by_policy(self):
        raw = load_fixture("webhook_valid_text.json")
        result = webhook_adapter.process_webhook_payload(raw, "sha256=deadbeef")
        self.assertEqual(result["status"], "BLOCKED_BY_POLICY")
        self.assertEqual(ledger.read_all(ledger.CONVERSATION_LEDGER), [])

    def test_forged_request_with_no_signature_header_is_blocked(self):
        raw = load_fixture("webhook_valid_text.json")
        result = webhook_adapter.process_webhook_payload(raw, "")
        self.assertEqual(result["status"], "BLOCKED_BY_POLICY")

    def test_signature_computed_with_wrong_secret_is_rejected(self):
        raw = load_fixture("webhook_valid_text.json")
        result = webhook_adapter.process_webhook_payload(raw, sign(raw, secret="not-the-real-secret"))
        self.assertEqual(result["status"], "BLOCKED_BY_POLICY")

    def test_malformed_json_payload_is_revision_required(self):
        raw = b"{not valid json"
        result = webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(result["status"], "REVISION_REQUIRED")

    def test_duplicate_delivery_is_deduped_not_double_ledgered(self):
        raw = load_fixture("webhook_valid_text.json")
        webhook_adapter.process_webhook_payload(raw, sign(raw))
        second = webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(second["duplicates"], ["wamid.FIXTURE_VALID_TEXT_0001"])
        self.assertEqual(len(ledger.read_all(ledger.CONVERSATION_LEDGER)), 1)

    def test_status_event_is_ledgered_regardless_of_arrival_order(self):
        # simulate the status webhook arriving before the original message event
        raw_status = load_fixture("webhook_status_delivered.json")
        result = webhook_adapter.process_webhook_payload(raw_status, sign(raw_status))
        self.assertEqual(result["status"], "SAFE_AUTOMATION_EXECUTED")
        events = ledger.read_all(ledger.CONVERSATION_LEDGER)
        self.assertEqual(events[0]["message_type"], "status")
        self.assertEqual(events[0]["content_reference"], "delivered")

    def test_unsupported_message_type_degrades_to_unknown_not_dropped(self):
        raw = load_fixture("webhook_unsupported_type.json")
        result = webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(result["status"], "SAFE_AUTOMATION_EXECUTED")
        self.assertEqual(result["events"][0]["message_type"], "unknown")

    def test_one_bad_event_does_not_block_next(self):
        payload = json.loads(load_fixture("webhook_valid_text.json"))
        good_message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        bad_message = dict(good_message)
        bad_message["id"] = "wamid.FIXTURE_BAD_0001"
        bad_message["timestamp"] = "not-a-number"  # forces int() to raise during normalization
        payload["entry"][0]["changes"][0]["value"]["messages"] = [bad_message, good_message]
        raw = json.dumps(payload).encode()

        result = webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["platform_message_id"], "wamid.FIXTURE_VALID_TEXT_0001")
        self.assertEqual(len(result["failed"]), 1)

    def test_challenge_handshake_success(self):
        challenge = webhook_adapter.verify_challenge({
            "hub.mode": "subscribe",
            "hub.verify_token": "fixture-verify-token-not-real",
            "hub.challenge": "12345",
        })
        self.assertEqual(challenge, "12345")

    def test_challenge_handshake_wrong_token_raises(self):
        with self.assertRaises(webhook_adapter.VerificationError):
            webhook_adapter.verify_challenge({
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "12345",
            })
