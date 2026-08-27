from whatsapp.src import ledger, reconcile
from whatsapp.tests.base import WhatsAppTestCase


class TestReconcile(WhatsAppTestCase):
    def test_delivered_status_maps_to_validated_complete(self):
        status_event = {
            "platform_message_id": "wamid.OUT_0001",
            "content_reference": "delivered",
        }
        record = reconcile.apply_status_event(status_event)
        self.assertEqual(record["state"], "VALIDATED_COMPLETE")

    def test_failed_status_maps_to_revision_required(self):
        status_event = {"platform_message_id": "wamid.OUT_0002", "content_reference": "failed"}
        record = reconcile.apply_status_event(status_event)
        self.assertEqual(record["state"], "REVISION_REQUIRED")

    def test_unmatched_platform_message_id_is_still_recorded(self):
        status_event = {"platform_message_id": "wamid.UNKNOWN_0003", "content_reference": "read"}
        record = reconcile.apply_status_event(status_event)
        self.assertFalse(record["matched_send_record"])
        entries = ledger.find(ledger.EXECUTION_LEDGER, platform_message_id="wamid.UNKNOWN_0003")
        self.assertEqual(len(entries), 1)

    def test_matched_send_record_true_when_prior_send_exists(self):
        ledger.append(ledger.EXECUTION_LEDGER, {
            "draft_id": "d1", "event_id": "e1",
            "platform_message_id": "wamid.OUT_0004", "state": "SAFE_AUTOMATION_EXECUTED",
        })
        status_event = {"platform_message_id": "wamid.OUT_0004", "content_reference": "read"}
        record = reconcile.apply_status_event(status_event)
        self.assertTrue(record["matched_send_record"])
