"""Deterministic evidence receipts (14)."""
import json

from omega import receipts
from omega.relationship import RelationshipMemory
from omega.tests.conftest import HUMAN, make_node


def scripted_run(node):
    rm = RelationshipMemory(node)
    c = rm.add_contact("Dana Reyes", primary="sms:+15550100", actor=HUMAN)
    rm.record_message(c, direction="OUT", text="Hi Dana, what is your timeline?", sent_at="2026-11-01T10:00:00Z",
                      source_ref="sms:1", actor=HUMAN)
    rm.record_message(c, direction="IN", text="We need it by end of March.", sent_at="2026-11-01T11:00:00Z",
                      source_ref="sms:2", actor="tool:sms-import")
    rm.compose(c, "discovery")
    return receipts.all_receipts(node)


def test_receipts_are_deterministic_for_the_same_device_and_inputs(tmp_path):
    a = make_node(tmp_path / "a", "phone")
    b = make_node(tmp_path / "b", "phone", clone_identity_from=tmp_path / "a" / "identity")
    ra, rb = scripted_run(a), scripted_run(b)
    assert len(ra) == 5   # contact, 2 messages, extracted fact, draft
    assert {r['detail']['event_type'] for r in ra} >= {'FACT_ASSERTED', 'DRAFT_PRODUCED'}
    assert [r["receipt_id"] for r in ra] == [r["receipt_id"] for r in rb]
    assert json.dumps(ra, sort_keys=True) == json.dumps(rb, sort_keys=True)  # Ed25519 signatures are deterministic too


def test_every_material_transition_has_a_chained_receipt(phone):
    rs = scripted_run(phone)
    assert rs[0]["prev"] is None and all(rs[i]["prev"] == rs[i - 1]["receipt_id"] for i in range(1, len(rs)))
    assert all(r["state_before"] != r["state_after"] for r in rs if r["type"] == "EVENT_APPENDED")
    assert receipts.verify_chain(phone) == []


def test_tampered_receipt_is_detected(phone):
    scripted_run(phone)
    phone.conn.execute("DROP TRIGGER receipts_no_update")   # an attacker with raw DB access
    body = json.loads(phone.conn.execute("SELECT body FROM receipts WHERE idx=2").fetchone()[0])
    body["detail"]["seq"] = 999
    phone.conn.execute("UPDATE receipts SET body=? WHERE idx=2", (json.dumps(body),))
    problems = {p[0] for p in receipts.verify_chain(phone)}
    assert "RECEIPT_ID_MISMATCH" in problems
    assert not phone.verify_integrity()["ok"]


def test_tampered_event_is_detected(phone):
    scripted_run(phone)
    phone.conn.execute("DROP TRIGGER events_immutable")
    row = phone.conn.execute("SELECT event_id, payload FROM events WHERE event_type='MESSAGE_RECORDED' LIMIT 1").fetchone()
    p = json.loads(row[1])
    p["text"] = "rewritten history"
    phone.conn.execute("UPDATE events SET payload=? WHERE event_id=?", (json.dumps(p), row[0]))
    assert ("PAYLOAD_HASH_MISMATCH", row[0]) in phone.verify_integrity()["problems"]
