import time
import uuid
from datetime import datetime, timedelta, timezone

from whatsapp.src import approval, classify, consent, draft as draft_mod, ledger, modes, normalize, outbound, schema
from whatsapp.tests.base import WhatsAppTestCase

TEST_PHONE = "15559998888"


def _make_inbound_event(contact_id=None, conversation_id="conv-abc", occurred_at=None):
    # contact_id must be derived the same way normalize.py derives it from a
    # real inbound message, so outbound.send()'s recipient-binding check
    # (hash_phone(to_phone) == contact_id) passes for these tests, exactly as
    # it would for a real webhook-sourced event.
    contact_id = contact_id or normalize.hash_phone(TEST_PHONE)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    event = schema.new_event(
        event_id=str(uuid.uuid4()),
        direction="inbound",
        occurred_at=occurred_at or now,
        received_at=now,
        contact_id=contact_id,
        conversation_id=conversation_id,
        platform_message_id=f"wamid.{uuid.uuid4()}",
        message_type="text",
        content_hash="0" * 64,
        consent_state="verified",
        retention_class="operational",
        evidence_class="customer-statement",
        authority_state="observe",
        processing_trace_id=str(uuid.uuid4()),
        provenance={"source": "whatsapp-cloud-api", "webhook_verified": True, "raw_payload_hash": "0" * 64},
    )
    ledger.append(ledger.CONVERSATION_LEDGER, event)
    return event


def _approved_draft(text="how much does this cost?", occurred_at=None):
    event = _make_inbound_event(occurred_at=occurred_at)
    classification = classify.classify(event, text)
    d = draft_mod.compile_draft(event, classification)
    approval.approve(d["draft_id"], actor="test-operator")
    return event, d


class TestOutbound(WhatsAppTestCase):
    def test_blocked_by_configuration_without_credentials(self):
        event, d = _approved_draft()
        consent.record_consent(event["contact_id"], "verified", source="test", can_respond=True)
        record = outbound.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(record["state"], "BLOCKED_BY_CONFIGURATION")

    def test_blocked_by_authority_when_not_approved(self):
        event = _make_inbound_event()
        classification = classify.classify(event, "how much does this cost?")
        d = draft_mod.compile_draft(event, classification)  # never approved
        record = outbound.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(record["state"], "BLOCKED_BY_AUTHORITY")

    def test_blocked_by_consent_when_revoked(self):
        event, d = _approved_draft()
        consent.record_consent(event["contact_id"], "revoked", source="test", can_respond=False)
        record = outbound.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(record["state"], "BLOCKED_BY_CONSENT")

    def test_emergency_stop_blocks_send_even_when_approved_and_configured(self):
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        event, d = _approved_draft()
        consent.record_consent(event["contact_id"], "verified", source="test", can_respond=True)
        modes.emergency_stop()
        record = outbound.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(record["state"], "BLOCKED_BY_AUTHORITY")

    def test_free_form_send_succeeds_within_csw_with_credentials(self):
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        event, d = _approved_draft()  # occurred_at defaults to now -> CSW open
        consent.record_consent(event["contact_id"], "verified", source="test", can_respond=True)

        captured = {}

        def fake_http_post(url, headers, body):
            captured["url"] = url
            captured["body"] = body
            return {"messages": [{"id": "wamid.SENT_0001"}]}

        record = outbound.send(d, event["contact_id"], to_phone="15559998888", http_post=fake_http_post)
        self.assertEqual(record["state"], "SAFE_AUTOMATION_EXECUTED")
        self.assertEqual(record["platform_message_id"], "wamid.SENT_0001")
        self.assertEqual(captured["body"]["type"], "text")

    def test_send_outside_csw_without_template_is_blocked_by_policy(self):
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        event, d = _approved_draft(occurred_at=old)
        consent.record_consent(event["contact_id"], "verified", source="test", can_respond=True)
        record = outbound.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(record["state"], "BLOCKED_BY_POLICY")

    def test_send_outside_csw_with_template_succeeds(self):
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        event, d = _approved_draft(occurred_at=old)
        consent.record_consent(event["contact_id"], "verified", source="test", can_respond=True)

        def fake_http_post(url, headers, body):
            return {"messages": [{"id": "wamid.SENT_0002"}]}

        record = outbound.send(
            d, event["contact_id"], to_phone="15559998888",
            template_name="forgeworld_followup_v1", http_post=fake_http_post,
        )
        self.assertEqual(record["state"], "SAFE_AUTOMATION_EXECUTED")
