"""End-to-end sandbox test proving the full chain from the mission's
completion gate (Section 22):
received -> authenticated -> normalized -> ledgered -> classified ->
context retrieved -> drafted -> authority enforced -> approved -> delivered
-> delivery status reconciled -> outcome recorded -- with a fully
reconstructable trace, no live network call.
"""
import os

from whatsapp.src import approval, ledger, pipeline, reconcile, webhook_adapter
from whatsapp.src import outbound as outbound_mod
from whatsapp.tests.base import WhatsAppTestCase, load_fixture, sign


class TestEndToEndSandbox(WhatsAppTestCase):
    def test_full_pipeline_sandbox_run(self):
        # 1. RECEIVED + AUTHENTICATED + NORMALIZED + LEDGERED
        raw = load_fixture("webhook_valid_text.json")
        intake = webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(intake["status"], "SAFE_AUTOMATION_EXECUTED")
        event = intake["events"][0]
        self.assertTrue(event["provenance"]["webhook_verified"])

        # 2. CLASSIFIED + DRAFTED (context retrieved from memory.log inside draft.compile_draft)
        text = "Hi, how much does a ForgeWorld diagnostic cost?"
        result = pipeline.handle_event(event, raw_text=text)
        self.assertEqual(result["kind"], "draft_ready")
        d = result["draft"]
        self.assertEqual(d["authority_state"], "draft")

        # 3. AUTHORITY ENFORCED: cannot send before approval
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        from whatsapp.src import consent as consent_mod
        consent_mod.record_consent(event["contact_id"], "verified", source="test_e2e", can_respond=True)

        premature = outbound_mod.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(premature["state"], "BLOCKED_BY_AUTHORITY")

        # 4. APPROVED (human, via CLI-backed workflow)
        approval_record = approval.approve(d["draft_id"], actor="jamdav688y@gmail.com")
        self.assertEqual(approval_record["authority_state"], "approved")

        # 5. DELIVERED (sandboxed -- no real network call)
        sent_ids = {}

        def fake_http_post(url, headers, body):
            sent_ids["to"] = body["to"]
            return {"messages": [{"id": "wamid.E2E_SENT_0001"}]}

        # Fixture uses a fixed historical timestamp, so the 24h customer
        # service window may or may not still be open depending on when this
        # test runs; supplying a template makes the send valid either way
        # without the test depending on wall-clock drift.
        send_record = outbound_mod.send(
            d, event["contact_id"], to_phone="15559998888",
            template_name="forgeworld_followup_v1", http_post=fake_http_post,
        )
        self.assertEqual(send_record["state"], "SAFE_AUTOMATION_EXECUTED")
        self.assertEqual(sent_ids["to"], "15559998888")

        # 6. DELIVERY STATUS RECONCILED
        status_event = {"platform_message_id": "wamid.E2E_SENT_0001", "content_reference": "delivered"}
        reconciliation = reconcile.apply_status_event(status_event)
        self.assertTrue(reconciliation["matched_send_record"])
        self.assertEqual(reconciliation["state"], "VALIDATED_COMPLETE")

        # 7. FULL TRACE RECONSTRUCTABLE from the execution ledger alone
        trace = ledger.find(ledger.EXECUTION_LEDGER, draft_id=d["draft_id"])
        states_seen = [r["state"] for r in trace]
        self.assertIn("READY_FOR_HUMAN_APPROVAL", states_seen)
        self.assertIn("APPROVED_AWAITING_SEND", states_seen)
        self.assertIn("BLOCKED_BY_AUTHORITY", states_seen)  # the premature attempt
        self.assertIn("SAFE_AUTOMATION_EXECUTED", states_seen)

    def test_no_governance_regression_when_credentials_absent(self):
        """Without live credentials, nothing can ever reach SAFE_AUTOMATION_EXECUTED
        for a send -- proves the system fails closed by default (mission Section 22)."""
        raw = load_fixture("webhook_valid_text.json")
        intake = webhook_adapter.process_webhook_payload(raw, sign(raw))
        event = intake["events"][0]
        result = pipeline.handle_event(event, raw_text="how much does this cost?")
        d = result["draft"]

        from whatsapp.src import consent as consent_mod
        consent_mod.record_consent(event["contact_id"], "verified", source="test", can_respond=True)
        approval.approve(d["draft_id"], actor="jamdav688y@gmail.com")

        record = outbound_mod.send(d, event["contact_id"], to_phone="15559998888", http_post=lambda *a, **k: {})
        self.assertEqual(record["state"], "BLOCKED_BY_CONFIGURATION")
