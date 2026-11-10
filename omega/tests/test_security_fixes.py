"""Directive 2, item 9: privacy and human-authorization defects, written as
attacks. Each test failed (or was impossible to pass) before the fix."""
import json
import sqlite3

import pytest

from omega import operator as op
from omega.events import Event, build_header, event_id_for
from omega.identity import PairingError, _write_secret
from omega.relationship import RelationshipMemory, contact_id_for
from omega.store import Node, StoreError
from omega.tasks import Executor, TaskQueue
from omega.tests.conftest import HUMAN, TEST_KDF, TEST_PASSPHRASE, make_node, run_pipe_sync


def forge_local_event(node, event_type, payload, actor=HUMAN):
    """What an agent with full file access can do: read the device signing key
    and write a perfectly signed event straight into the database, bypassing
    append() and its attestation check. It cannot produce `_operator`."""
    with node.tx() as conn:
        row = conn.execute("SELECT seq, event_id FROM events WHERE device_id=? ORDER BY seq DESC LIMIT 1",
                           (node.device_id,)).fetchone()
        h = build_header(event_type=event_type, device_id=node.device_id, actor_id=actor, actor_kind="HUMAN",
                         seq=row[0] + 1, prev=row[1], ts=node.clock(), payload=payload,
                         parents=[payload["task_event"]] if "task_event" in payload else [], privacy="PRIVATE",
                         links=[f"task:{payload['task_id']}"] if "task_id" in payload else [])
        ev = Event(h, node.identity.sign(event_id_for(h).encode()), payload)
        node._insert(conn, ev, "LOCAL", None)
    return ev


def test_agent_with_file_access_but_no_passphrase_cannot_authorize_execution(phone):
    calls = []
    q = TaskQueue(phone, {"send": Executor(lambda a: calls.append(a) or "sent", external=True)})
    t = q.queue("send", {"to": "x"}, actor="model:agent", external_effect=True)
    with pytest.raises(StoreError) as e:
        q.authorize(t, actor=HUMAN)                       # the API path: refused
    assert e.value.code == "OPERATOR_ATTESTATION_REQUIRED"
    task_ev = q._task_event(t)
    forge_local_event(phone, "TASK_AUTHORIZED", {"task_id": t, "task_event": event_id_for(task_ev.header),
                                                 "authorized_device": phone.device_id, "note": "forged"})
    forge_local_event(phone, "TASK_AUTHORIZED", {"task_id": t, "task_event": event_id_for(task_ev.header),
                                                 "authorized_device": phone.device_id, "note": "forged",
                                                 "_operator": {"operator_id": phone.op.operator_id, "sig": "AAAA"}})
    assert dict(q.run_once())[t] == "AWAITING_AUTHORIZATION"
    assert calls == []
    assert phone.verify_integrity()["ok"]   # the forged rows are validly signed history, and still ineffective


def test_attestation_cannot_be_replayed_onto_a_different_payload(phone):
    q = TaskQueue(phone, {"send": Executor(lambda a: "sent", external=True)})
    t1 = q.queue("send", {"to": "a"}, actor=HUMAN, external_effect=True)
    t2 = q.queue("send", {"to": "b"}, actor=HUMAN, external_effect=True)
    good = q.authorize(t1, actor=HUMAN, operator=phone.op)
    stolen = good.payload["_operator"]
    ev2 = q._task_event(t2)
    forge_local_event(phone, "TASK_AUTHORIZED", {"task_id": t2, "task_event": event_id_for(ev2.header),
                                                 "authorized_device": phone.device_id, "note": "operator authorized",
                                                 "_operator": stolen})
    out = dict(q.run_once())
    assert out == {t1: "SUCCEEDED", t2: "AWAITING_AUTHORIZATION"}


def test_peer_cannot_purge_my_data_without_its_operator(paired):
    phone, pc = paired
    note = phone.append("NOTE_RECORDED", {"text": "important"}, actor=HUMAN)
    run_pipe_sync(phone, pc)
    # a compromised PC process forges a deletion signed by the PC device key
    forge_local_event(pc, "DELETION_AUTHORIZED", {"target_event": note.event_id, "reason": "forged"})
    run_pipe_sync(pc, phone)
    assert phone.get(note.event_id).payload == {"text": "important"}
    reasons = [r[0] for r in phone.conn.execute("SELECT reason FROM quarantine")]
    assert any(r.startswith("UNATTESTED_DELETION_AUTHORIZED") for r in reasons)
    # a genuine, attested deletion from the PC operator does propagate
    pc.authorize_deletion(note.event_id, "erasure request", actor=HUMAN, operator=pc.op)
    run_pipe_sync(pc, phone)
    assert phone.payload_state(note.event_id) == "PURGED"


def test_operator_key_at_rest_and_identity_binding(phone, tmp_path):
    doc = json.loads((phone.path / "operator" / "operator.json").read_text())
    assert set(doc) == {"v", "name", "operator_id", "pub", "kdf", "salt", "nonce", "ct"}
    with pytest.raises(op.OperatorError) as e:
        phone.unlock_operator("wrong passphrase!!")
    assert e.value.code == "PASSPHRASE_WRONG"
    target = phone.append("NOTE_RECORDED", {"text": "x"}, actor=HUMAN)
    with pytest.raises(StoreError) as e:
        phone.authorize_deletion(target.event_id, "r", actor="human:mallory", operator=phone.op)
    assert e.value.code == "ACTOR_NOT_OPERATOR"
    other = make_node(tmp_path / "o", "other")
    with pytest.raises(StoreError) as e:   # another device's operator does not count here
        phone.authorize_deletion(target.event_id, "r", actor=HUMAN, operator=other.op)
    assert e.value.code == "OPERATOR_ATTESTATION_REQUIRED"
    with pytest.raises(op.OperatorError):
        op.create(phone.path / "operator", "operator", TEST_PASSPHRASE, TEST_KDF)   # never overwritten


def test_pairing_requires_registered_operators(tmp_path):
    a = make_node(tmp_path / "a", "a", operator=False)
    with pytest.raises(PairingError):
        a.pairing_offer()


def test_contact_ids_cannot_be_recomputed_from_a_phone_number(paired):
    phone, pc = paired
    rp, rc = RelationshipMemory(phone), RelationshipMemory(pc)
    cid = rp.add_contact("Dana Reyes", primary="sms:+15550100", actor=HUMAN)
    assert cid != contact_id_for("sms:+15550100")                 # the old, enumerable derivation
    assert rp.add_contact("Dana R.", primary="SMS:+15550100 ", actor=HUMAN) == cid   # same person, same id
    run_pipe_sync(phone, pc)
    assert rc.add_contact("Dana Reyes", primary="sms:+15550100", actor=HUMAN) == cid  # reused after sync
    # the header link a peer sees is not derivable from the number without this device's secret
    link = phone.events("CONTACT_ASSERTED")[0].header["links"][0]
    assert link == f"contact:{cid}"
    assert pc.identity.secret_tag("contact-id", "sms:+15550100")[:24] != cid[3:]


@pytest.mark.parametrize("data", [bytes(range(256)), b"\n" * 32, b"\r\n\x1a\x00" * 8])
def test_key_file_bytes_round_trip_exactly(tmp_path, data):
    """Windows regression (directive 2, item 3): before O_BINARY a key byte 0x0A
    was written as 0x0D 0x0A in text mode. On Linux this passes either way. It
    is the check scripts/omega-proof.ps1 runs on the real Windows machine."""
    p = tmp_path / "k.key"
    _write_secret(p, data)
    assert p.read_bytes() == data


def test_old_database_is_migrated(tmp_path):
    n = make_node(tmp_path / "n", "n")
    n.close()
    db = sqlite3.connect(str(tmp_path / "n" / "node.db"))
    db.execute("ALTER TABLE peers RENAME TO peers_new")
    db.execute("CREATE TABLE peers(device_id TEXT PRIMARY KEY, label TEXT NOT NULL, sign_pub TEXT NOT NULL,"
               " kx_pub TEXT NOT NULL, max_privacy TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,"
               " last_vector TEXT NOT NULL DEFAULT '{}')")
    db.execute("DROP TABLE peers_new")
    db.commit()
    db.close()
    n2 = Node.open(tmp_path / "n")
    assert "operator_pub" in {r[1] for r in n2.conn.execute("PRAGMA table_info(peers)")}
    n2.close()
