"""Stage B: canonical evidence kernel -- schema, hashing, append-only history,
provenance, corrections, privacy, authorized deletion, retention, governance."""
import json
import sqlite3

import pytest

from omega import policy
from omega.canonical import CanonicalError, canonical, digest
from omega.events import EventError, build_header, event_id_for, validate
from omega.store import StoreError
from omega.tests.conftest import HUMAN


def test_canonical_serialization_is_deterministic_and_strict():
    a = {"b": 1, "a": [3, {"z": "é", "y": None}]}
    b = {"a": [3, {"y": None, "z": "é"}], "b": 1}
    assert canonical(a) == canonical(b) == '{"a":[3,{"y":null,"z":"é"}],"b":1}'.encode()
    assert digest("x", a) == digest("x", b) != digest("y", a)  # domain separated
    with pytest.raises(CanonicalError):
        canonical({"amount": 1.5})  # floats are never hashed: money is integer minor units


def test_event_has_every_required_dimension(phone):
    ev = phone.append("NOTE_RECORDED", {"text": "first"}, actor=HUMAN,
                      provenance=[{"kind": "source", "ref": "voice-memo:1"}], links=["project:omega"])
    h = ev.header
    for k in ("schema", "event_type", "device_id", "actor_id", "actor_kind", "seq", "prev", "ts", "parents",
              "payload_hash", "artifacts", "provenance", "links", "privacy", "scope", "verification",
              "supersedes", "corrects"):
        assert k in h
    assert h["schema"] == "fw.omega.event/1" and h["seq"] == 1 and h["prev"] is None
    assert ev.event_id.startswith("ev_") and len(ev.event_id) == 67
    ev2 = phone.append("NOTE_RECORDED", {"text": "second"}, actor=HUMAN)
    assert ev2.header["seq"] == 2 and ev2.header["prev"] == ev.event_id


def test_history_is_append_only_at_the_database_level(phone):
    ev = phone.append("NOTE_RECORDED", {"text": "keep me"}, actor=HUMAN)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        phone.conn.execute("DELETE FROM events")
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        phone.conn.execute("UPDATE events SET header='{}' WHERE event_id=?", (ev.event_id,))
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        phone.conn.execute("UPDATE events SET payload='{\"text\":\"rewritten\"}' WHERE event_id=?", (ev.event_id,))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        phone.conn.execute("DELETE FROM receipts")
    assert phone.get(ev.event_id).payload == {"text": "keep me"}


def test_correction_is_a_new_event_and_original_survives(phone):
    orig = phone.append("NOTE_RECORDED", {"text": "meeting is on Tuesday"}, actor=HUMAN)
    fix = phone.append("NOTE_RECORDED", {"text": "meeting is on Wednesday"}, actor=HUMAN, corrects=orig.event_id)
    assert phone.get(orig.event_id).payload["text"] == "meeting is on Tuesday"
    assert fix.header["corrects"] == orig.event_id and orig.event_id in fix.header["parents"]
    assert orig.event_id in phone.ancestors(fix.event_id)


def test_source_artifact_stored_separately_from_derived_text(phone):
    raw = b"From: Dana\r\nSubject: budget\r\n\r\nWe can do $5,000."
    ev = phone.append("ARTIFACT_INGESTED", {"sha256": __import__("hashlib").sha256(raw).hexdigest(),
                                            "media_type": "message/rfc822", "locator": "mail:inbox/42", "size": len(raw)},
                      actor="tool:mail-import", artifact_data=[(raw, "message/rfc822")],
                      provenance=[{"kind": "source", "ref": "mail:inbox/42"}])
    sha = ev.header["artifacts"][0]
    assert phone.artifact(sha) == raw
    assert ev.payload["sha256"] == sha


def test_message_without_source_provenance_is_refused(phone):
    with pytest.raises(StoreError) as e:
        phone.append("MESSAGE_RECORDED", {"contact_id": "ct_x", "conversation_id": "c", "channel": "sms",
                                          "direction": "IN", "text": "hi", "sent_at": "2026-11-01T00:00:00Z"},
                     actor="tool:import")
    assert e.value.code == "PROVENANCE_MISSING"


def test_governance_and_verification_are_human_only(phone):
    target = phone.append("NOTE_RECORDED", {"text": "x"}, actor=HUMAN)
    for actor in ("model:llama", "tool:x", "system:y"):
        with pytest.raises(StoreError) as e:
            phone.append("DELETION_AUTHORIZED", {"target_event": target.event_id, "reason": "r"}, actor=actor)
        assert e.value.code == "ACTOR_NOT_PERMITTED"
    with pytest.raises(StoreError) as e:
        phone.append("NOTE_RECORDED", {"text": "I verified this"}, actor="model:llama", verification="VERIFIED")
    assert e.value.code == "ACTOR_NOT_PERMITTED"
    with pytest.raises(StoreError) as e:
        phone.append("PROMOTION_DECISION", {"experiment_id": "x", "decision": "PROMOTE", "rollback_point": "a",
                                            "gate_event": target.event_id}, actor="model:planner")
    assert e.value.code == "ACTOR_NOT_PERMITTED"


def test_validate_rejects_tampered_payload():
    payload = {"text": "a"}
    h = build_header(event_type="NOTE_RECORDED", device_id="dev_" + "0" * 32, actor_id=HUMAN, actor_kind="HUMAN",
                     seq=1, prev=None, ts="2026-11-01T00:00:00Z", payload=payload)
    validate(h, payload)
    with pytest.raises(EventError) as e:
        validate(h, {"text": "b"})
    assert e.value.code == "PAYLOAD_HASH_MISMATCH"


def test_authorized_deletion_purges_payload_keeps_verifiable_header(phone):
    secret = phone.append("NOTE_RECORDED", {"text": "card number 4111 1111"}, actor=HUMAN,
                          artifact_data=[(b"scan-bytes", "image/png")])
    sha = secret.header["artifacts"][0]
    assert phone.search("4111")
    phone.authorize_deletion(secret.event_id, "contains a card number", actor=HUMAN)
    assert phone.get(secret.event_id).payload is None
    assert phone.payload_state(secret.event_id) == "PURGED"
    assert phone.search("4111") == []
    assert phone.artifact(sha) is None
    assert phone.verify_integrity()["ok"]   # header + chain still verify


def test_retention_policy_purges_deterministically(phone):
    old = phone.append("NOTE_RECORDED", {"text": "old note"}, actor=HUMAN)
    phone.append("RETENTION_POLICY", {"event_type": "NOTE_RECORDED", "max_age_days": 30}, actor=HUMAN,
                 privacy="INTERNAL")
    import calendar, time
    now = calendar.timegm(time.strptime("2027-01-15T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    purged = phone.apply_retention(now)
    assert purged == [old.event_id]
    assert phone.apply_retention(now) == []  # idempotent
    assert phone.verify_integrity()["ok"]


def test_policy_tables_are_closed():
    assert set(policy.EVENT_TYPES) >= {"TASK_AUTHORIZED", "PROMOTION_DECISION", "DELETION_AUTHORIZED"}
    for et in ("TASK_AUTHORIZED", "PROMOTION_DECISION", "DELETION_AUTHORIZED", "CONFLICT_RESOLVED",
               "PAYMENT_VERIFIED", "PEER_PAIRED", "ACCESS_REVOKED", "RETENTION_POLICY"):
        assert policy.EVENT_TYPES[et][0] == ("HUMAN",), et
