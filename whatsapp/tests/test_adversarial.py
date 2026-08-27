"""Adversarial / edge-case hardening tests added during pre-merge security
certification of PR #4: concurrency, replay, ledger corruption, partial
writes, duplicate approvals, forged delivery states, and sends attempted
while EMERGENCY_STOP is active. None of these make a live network call or
weaken any existing fail-closed behavior -- they only prove it holds under
adversarial conditions.
"""
import json
import threading
import time
import uuid

from whatsapp.src import (
    approval, classify, consent, draft as draft_mod, ledger, modes,
    normalize, outbound, reconcile, schema, webhook_adapter,
)
from whatsapp.tests.base import WhatsAppTestCase, load_fixture, sign

TEST_PHONE = "15559998888"


def _approved_draft(text="how much does this cost?"):
    contact_id = normalize.hash_phone(TEST_PHONE)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    event = schema.new_event(
        event_id=str(uuid.uuid4()),
        direction="inbound",
        occurred_at=now,
        received_at=now,
        contact_id=contact_id,
        conversation_id="conv-adversarial",
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
    classification = classify.classify(event, text)
    d = draft_mod.compile_draft(event, classification)
    consent.record_consent(contact_id, "verified", source="test", can_respond=True)
    approval.approve(d["draft_id"], actor="test-operator")
    return event, d


class TestConcurrency(WhatsAppTestCase):
    def test_concurrent_ledger_appends_are_not_interleaved(self):
        errors = []

        def writer(n):
            try:
                for i in range(50):
                    ledger.append(ledger.CONVERSATION_LEDGER, {"writer": n, "seq": i, "pad": "x" * 200})
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # Every line must be independently valid JSON -- a single corrupted,
        # interleaved line here would prove the file lock isn't working.
        records = ledger.read_all(ledger.CONVERSATION_LEDGER)
        self.assertEqual(len(records), 8 * 50)
        seen = {(r["writer"], r["seq"]) for r in records}
        self.assertEqual(len(seen), 400)  # no writes silently lost either

    def test_concurrent_webhook_deliveries_for_different_messages_all_ledgered(self):
        raw_template = json.loads(load_fixture("webhook_valid_text.json"))
        errors = []

        def deliver(n):
            try:
                payload = json.loads(json.dumps(raw_template))
                msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
                msg["id"] = f"wamid.CONCURRENT_{n}"
                raw = json.dumps(payload).encode()
                result = webhook_adapter.process_webhook_payload(raw, sign(raw))
                if result["status"] != "SAFE_AUTOMATION_EXECUTED":
                    errors.append(result)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=deliver, args=(n,)) for n in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        events = ledger.read_all(ledger.CONVERSATION_LEDGER)
        self.assertEqual(len(events), 10)


class TestReplay(WhatsAppTestCase):
    def test_replaying_the_same_webhook_many_times_never_duplicates(self):
        raw = load_fixture("webhook_valid_text.json")
        for _ in range(5):
            webhook_adapter.process_webhook_payload(raw, sign(raw))
        self.assertEqual(len(ledger.read_all(ledger.CONVERSATION_LEDGER)), 1)

    def test_replaying_an_approved_send_is_idempotent_not_a_double_send(self):
        event, d = _approved_draft()
        call_count = {"n": 0}

        def fake_http_post(url, headers, body):
            call_count["n"] += 1
            return {"messages": [{"id": "wamid.REPLAY_SENT_0001"}]}

        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"

        first = outbound.send(d, event["contact_id"], to_phone=TEST_PHONE, http_post=fake_http_post)
        second = outbound.send(d, event["contact_id"], to_phone=TEST_PHONE, http_post=fake_http_post)
        third = outbound.send(d, event["contact_id"], to_phone=TEST_PHONE, http_post=fake_http_post)

        self.assertEqual(first["state"], "SAFE_AUTOMATION_EXECUTED")
        self.assertEqual(second["state"], "VALIDATED_COMPLETE")
        self.assertEqual(third["state"], "VALIDATED_COMPLETE")
        self.assertEqual(call_count["n"], 1)  # the real send only ever happened once


class TestLedgerCorruption(WhatsAppTestCase):
    def test_one_corrupted_line_does_not_break_reading_the_rest(self):
        ledger.append(ledger.CONVERSATION_LEDGER, {"event_id": "good-1"})
        with open(ledger.CONVERSATION_LEDGER, "a") as f:
            f.write("{not valid json at all\n")
        ledger.append(ledger.CONVERSATION_LEDGER, {"event_id": "good-2"})

        records = ledger.read_all(ledger.CONVERSATION_LEDGER)
        ids = [r["event_id"] for r in records]
        self.assertEqual(ids, ["good-1", "good-2"])

    def test_corrupted_line_is_preserved_for_recovery_not_silently_lost(self):
        ledger.append(ledger.CONVERSATION_LEDGER, {"event_id": "good-1"})
        with open(ledger.CONVERSATION_LEDGER, "a") as f:
            f.write("{definitely not json\n")
        ledger.read_all(ledger.CONVERSATION_LEDGER)

        corrupt_path = ledger.CONVERSATION_LEDGER.with_suffix(".jsonl.corrupt")
        self.assertTrue(corrupt_path.exists())
        self.assertIn("definitely not json", corrupt_path.read_text())

    def test_partial_write_truncated_mid_line_does_not_break_prior_records(self):
        ledger.append(ledger.CONVERSATION_LEDGER, {"event_id": "good-1"})
        with open(ledger.CONVERSATION_LEDGER, "a") as f:
            f.write('{"event_id": "trunc')  # simulates a crash mid-write, no trailing newline

        records = ledger.read_all(ledger.CONVERSATION_LEDGER)
        self.assertEqual([r["event_id"] for r in records], ["good-1"])

    def test_empty_ledger_file_reads_as_empty_list(self):
        ledger.CONVERSATION_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        ledger.CONVERSATION_LEDGER.touch()
        self.assertEqual(ledger.read_all(ledger.CONVERSATION_LEDGER), [])


class TestDuplicateApprovals(WhatsAppTestCase):
    def test_double_approve_before_send_is_harmless(self):
        event, d = _approved_draft()
        # approve() was already called once inside _approved_draft(); a
        # second approval before any send must not raise or corrupt state.
        record = approval.approve(d["draft_id"], actor="second-approver")
        self.assertEqual(record["authority_state"], "approved")

    def test_cannot_approve_a_draft_that_was_already_sent(self):
        event, d = _approved_draft()
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        outbound.send(d, event["contact_id"], to_phone=TEST_PHONE,
                       http_post=lambda *a, **k: {"messages": [{"id": "wamid.X"}]})

        with self.assertRaises(ValueError):
            approval.approve(d["draft_id"], actor="late-approver")

    def test_cannot_reject_a_draft_already_marked_not_an_opportunity(self):
        event, d = _approved_draft()
        approval.mark_not_opportunity(d["draft_id"], actor="test-operator")
        with self.assertRaises(ValueError):
            approval.reject(d["draft_id"], actor="test-operator")


class TestForgedDeliveryStates(WhatsAppTestCase):
    def test_forged_status_for_a_message_id_that_was_never_sent_is_flagged_unmatched(self):
        forged = {"platform_message_id": "wamid.NEVER_SENT_BY_US", "content_reference": "delivered"}
        record = reconcile.apply_status_event(forged)
        self.assertFalse(record["matched_send_record"])
        # It is recorded for audit, but never presented as confirming a real send.

    def test_forged_read_receipt_does_not_retroactively_authorize_anything(self):
        # A "read" status for a random id must never appear anywhere as an
        # APPROVED_AWAITING_SEND or authority-bearing record.
        forged = {"platform_message_id": "wamid.FORGED_READ", "content_reference": "read"}
        reconcile.apply_status_event(forged)
        matches = ledger.find(ledger.EXECUTION_LEDGER, platform_message_id="wamid.FORGED_READ")
        for m in matches:
            self.assertNotIn(m["state"], {"APPROVED_AWAITING_SEND", "SAFE_AUTOMATION_EXECUTED"})


class TestOutboundDuringEmergencyStop(WhatsAppTestCase):
    def test_send_attempted_mid_conversation_after_stop_is_blocked(self):
        event, d = _approved_draft()
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"

        modes.emergency_stop()

        sent = {"called": False}

        def fake_http_post(*a, **k):
            sent["called"] = True
            return {"messages": [{"id": "wamid.SHOULD_NOT_SEND"}]}

        record = outbound.send(d, event["contact_id"], to_phone=TEST_PHONE, http_post=fake_http_post)
        self.assertEqual(record["state"], "BLOCKED_BY_AUTHORITY")
        self.assertFalse(sent["called"])

    def test_stop_blocks_every_pending_draft_not_just_one(self):
        _, d1 = _approved_draft(text="how much does this cost?")
        _, d2 = _approved_draft(text="can we schedule a call?")
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"
        modes.emergency_stop()

        contact_id = normalize.hash_phone(TEST_PHONE)
        r1 = outbound.send(d1, contact_id, to_phone=TEST_PHONE, http_post=lambda *a, **k: {})
        r2 = outbound.send(d2, contact_id, to_phone=TEST_PHONE, http_post=lambda *a, **k: {})
        self.assertEqual(r1["state"], "BLOCKED_BY_AUTHORITY")
        self.assertEqual(r2["state"], "BLOCKED_BY_AUTHORITY")


class TestRecipientBinding(WhatsAppTestCase):
    def test_send_to_a_different_phone_than_the_draft_was_approved_for_is_blocked(self):
        event, d = _approved_draft()
        import os
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "fixture-token"
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1000000000000001"

        record = outbound.send(
            d, event["contact_id"], to_phone="15550009999",  # different number
            http_post=lambda *a, **k: {"messages": [{"id": "wamid.SHOULD_NOT_SEND"}]},
        )
        self.assertEqual(record["state"], "BLOCKED_BY_AUTHORITY")


class TestSaltConfiguration(WhatsAppTestCase):
    def test_missing_salt_fails_loudly_not_with_a_weak_default(self):
        import os
        del os.environ["WHATSAPP_ID_SALT"]
        with self.assertRaises(normalize.ConfigurationError):
            normalize.hash_phone("15559998888")
