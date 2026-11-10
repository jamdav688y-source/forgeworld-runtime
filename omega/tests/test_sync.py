"""Stage E: pairing, authentication, replay protection, duplicates,
interruption, conflicts, privacy, and the real TCP transport."""
import json
import threading

import pytest

from omega import reconcile, sync
from omega.identity import PairingError, parse_offer, short_auth_string
from omega.relationship import RelationshipMemory
from omega.tests.conftest import HUMAN, make_node, pair, run_pipe_sync


# ---------------------------------------------------------------- pairing / auth
def test_pairing_requires_matching_short_authentication_string(phone, pc):
    oa = parse_offer(phone.pairing_offer())
    ob = parse_offer(pc.pairing_offer())
    good = short_auth_string(oa, ob)
    assert good == short_auth_string(ob, oa)  # both screens show the same digits
    bad = f"{(int(good) + 1) % 1000000:06d}"
    with pytest.raises(PairingError):
        phone.add_peer(ob, oa, bad, actor=HUMAN, operator=phone.op)
    with pytest.raises(PairingError):
        phone.add_peer(ob, oa, good, actor="model:assistant", operator=phone.op)
    with pytest.raises(PairingError):
        phone.add_peer(ob, oa, good, actor=HUMAN)          # no unlocked operator key
    phone.add_peer(ob, oa, good, actor=HUMAN, operator=phone.op)
    assert phone.peer(pc.device_id)["max_privacy"] == "PRIVATE"


def test_man_in_the_middle_offer_changes_the_sas(phone, pc, tmp_path):
    mallory = make_node(tmp_path / "m", "mallory")
    oa = parse_offer(phone.pairing_offer())
    ob = parse_offer(pc.pairing_offer())
    om = parse_offer(mallory.pairing_offer())
    assert short_auth_string(oa, om) != short_auth_string(oa, ob)


def test_unpaired_device_is_refused_by_both_sides(phone, pc):
    ri, rr = run_pipe_sync(phone, pc)
    assert isinstance(ri, sync.SyncError) and ri.code == "REFUSED_BY_PEER"
    assert isinstance(rr, sync.SyncError) and rr.code == "PEER_UNKNOWN"
    assert pc.vector().get(phone.device_id, 0) == 0 or phone.device_id not in pc.vector()


def test_impostor_with_copied_device_id_fails_authentication(paired, tmp_path):
    phone, pc = paired
    impostor = make_node(tmp_path / "imp", "impostor")
    impostor.device_id = phone.device_id  # claims to be the phone, but holds a different key
    impostor.conn.execute("INSERT INTO peers(device_id,label,sign_pub,kx_pub,max_privacy) VALUES(?,?,?,?,?)",
                          (pc.device_id, "pc", *[x for x in (
                              __import__("omega.identity", fromlist=["b64e"]).b64e(pc.identity.sign_pub),
                              __import__("omega.identity", fromlist=["b64e"]).b64e(pc.identity.kx_pub))], "PRIVATE"))
    ri, rr = run_pipe_sync(impostor, pc)
    assert isinstance(rr, sync.SyncError) and rr.code == "PEER_AUTHENTICATION_FAILED"


def test_replayed_hello_nonce_is_refused(paired):
    phone, pc = paired
    ca, cb = sync.PipeChannel.pair()
    t = threading.Thread(target=lambda: _swallow(lambda: sync.handshake_responder(pc, cb)))
    t.start()
    sync.handshake_initiator(phone, ca, _nonce="ab" * 32)
    t.join()
    ca, cb = sync.PipeChannel.pair()
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", _swallow(lambda: sync.handshake_responder(pc, cb))))
    t.start()
    with pytest.raises(sync.SyncError) as e:
        sync.handshake_initiator(phone, ca, _nonce="ab" * 32)
    t.join()
    assert e.value.code == "REFUSED_BY_PEER"
    assert out["r"].code == "REPLAY_DETECTED"


def _swallow(fn):
    try:
        return fn()
    except Exception as exc:
        return exc


def test_replayed_or_tampered_encrypted_frame_is_rejected(paired):
    phone, pc = paired
    ca, cb = sync.PipeChannel.pair()
    res = {}
    t = threading.Thread(target=lambda: res.setdefault("r", sync.handshake_responder(pc, cb)))
    t.start()
    sci, _ = sync.handshake_initiator(phone, ca)
    t.join()
    scr, _ = res["r"]
    # capture a frame, deliver it, then replay it
    captured = []
    real_send = ca.send
    ca.send = lambda d: (captured.append(d), real_send(d))
    sci.send({"t": "VECTOR", "vector": {}, "withheld": []})
    assert scr.recv()["t"] == "VECTOR"
    cb.inbox.put(captured[0])
    with pytest.raises(sync.SyncError) as e:
        scr.recv()
    assert e.value.code == "FRAME_REPLAYED_OR_REORDERED"
    # tampered ciphertext with the correct counter
    frame = bytearray(captured[0])
    frame[:12] = (1).to_bytes(12, "big")
    frame[-1] ^= 1
    cb.inbox.put(bytes(frame))
    with pytest.raises(sync.SyncError) as e:
        scr.recv()
    assert e.value.code == "FRAME_AUTHENTICATION_FAILED"


def test_revoked_peer_cannot_sync(paired):
    phone, pc = paired
    pc.revoke_peer(phone.device_id, actor=HUMAN, operator=pc.op)
    ri, rr = run_pipe_sync(phone, pc)
    assert isinstance(rr, sync.SyncError) and rr.code == "PEER_REVOKED"


# ---------------------------------------------------------------- data transfer
def test_sync_converges_and_duplicates_are_rejected(paired):
    phone, pc = paired
    for i in range(5):
        phone.append("NOTE_RECORDED", {"text": f"phone note {i}"}, actor=HUMAN)
    pc.append("NOTE_RECORDED", {"text": "pc note"}, actor=HUMAN)
    ri, rr = run_pipe_sync(phone, pc)
    assert ri.complete and rr.complete
    shared = {k: v for k, v in phone.vector().items()}
    assert pc.vector() == shared
    # second session moves nothing; replaying every event is an idempotent no-op
    ri2, rr2 = run_pipe_sync(pc, phone)
    assert ri2.imported == [] and rr2.imported == []
    for env in phone.events_for_peer({}, "PRIVATE", limit=1000):
        r = pc.import_event(env, phone.device_id)
        assert r.code == "DUPLICATE"
    assert pc.verify_integrity()["ok"] and phone.verify_integrity()["ok"]


@pytest.mark.parametrize("fault_after,side", [(1, "initiator"), (2, "initiator"), (3, "responder"),
                                               (4, "initiator"), (5, "responder")])
def test_interrupted_sync_resumes_without_loss_or_duplication(paired, fault_after, side, monkeypatch):
    phone, pc = paired
    monkeypatch.setattr(sync, "BATCH", 3)  # many frames, so faults land mid-stream
    for i in range(10):
        phone.append("NOTE_RECORDED", {"text": f"p{i}"}, actor=HUMAN)
    for i in range(7):
        pc.append("NOTE_RECORDED", {"text": f"c{i}"}, actor=HUMAN)
    ri, rr = run_pipe_sync(phone, pc, fault_after=fault_after, fault_side=side)
    assert not (getattr(ri, "complete", False) and getattr(rr, "complete", False))
    assert phone.verify_integrity()["ok"] and pc.verify_integrity()["ok"]
    partial = pc.vector().get(phone.device_id, 0)
    assert 0 <= partial <= 11
    ri, rr = run_pipe_sync(phone, pc)
    assert ri.complete and rr.complete
    assert phone.vector() == pc.vector()
    assert phone.state_digest() == pc.state_digest()
    kinds = {r["type"] for r in __import__("omega.receipts", fromlist=["x"]).all_receipts(pc)}
    assert "SYNC_SESSION" in kinds


def test_concurrent_conflicting_updates_are_recorded_not_merged(paired):
    phone, pc = paired
    rm_p, rm_c = RelationshipMemory(phone), RelationshipMemory(pc)
    cid = rm_p.add_contact("Dana Reyes", primary="sms:+15550100", actor=HUMAN)
    run_pipe_sync(phone, pc)
    rm_p.assert_fact(cid, "timeline", "end of March", basis="OPERATOR", actor=HUMAN)  # offline, concurrently
    rm_c.assert_fact(cid, "timeline", "end of April", basis="OPERATOR", actor=HUMAN)
    ri, rr = run_pipe_sync(phone, pc)
    key = f"fact|contact:{cid}|timeline"
    for node in (phone, pc):
        r = reconcile.resolve(node, key)
        assert r["status"] == "CONFLICTED" and r["value"] is None
        assert sorted(r["candidates"].values()) == ["end of April", "end of March"]
        assert [c["key"] for c in reconcile.open_conflicts(node)] == [key]
    assert key in ri.conflicts and key in rr.conflicts
    # the draft engine never silently picks one
    assert rm_c.context(cid)["facts"]["timeline"]["status"] == "CONFLICTED"
    # human resolution on one device converges everywhere
    reconcile.resolve_conflict(pc, key, "end of April", actor=HUMAN, note="confirmed by phone call")
    run_pipe_sync(pc, phone)
    for node in (phone, pc):
        r = reconcile.resolve(node, key)
        assert (r["status"], r["value"]) == ("RESOLVED", "end of April")
        assert reconcile.open_conflicts(node) == []


def test_resolution_is_independent_of_import_order(paired, tmp_path):
    phone, pc = paired
    third = make_node(tmp_path / "t", "third")
    pair(third, phone)
    pair(third, pc)
    phone.append("FACT_ASSERTED", {"subject": "contact:x", "attribute": "a", "value": "1", "basis": "OPERATOR"},
                 actor=HUMAN, links=["contact:x"])
    pc.append("FACT_ASSERTED", {"subject": "contact:x", "attribute": "a", "value": "2", "basis": "OPERATOR"},
              actor=HUMAN, links=["contact:x"])
    run_pipe_sync(third, phone)
    run_pipe_sync(third, pc)
    run_pipe_sync(pc, phone)
    rs = [reconcile.resolve(n, "fact|contact:x|a") for n in (phone, pc, third)]
    assert all(r["status"] == "CONFLICTED" for r in rs)
    assert rs[0]["heads"] == rs[1]["heads"] == rs[2]["heads"]


def test_equivocation_is_detected_and_quarantined(paired, tmp_path):
    phone, pc = paired
    phone.append("NOTE_RECORDED", {"text": "honest"}, actor=HUMAN)
    run_pipe_sync(phone, pc)
    # a forked copy of the phone signs a different event with the same seq
    import shutil
    from omega.store import Node
    phone.close()
    shutil.copytree(phone.path, tmp_path / "fork")
    fork = Node.open(tmp_path / "fork")
    honest = Node.open(phone.path)
    honest.append("NOTE_RECORDED", {"text": "A"}, actor=HUMAN)
    fork.append("NOTE_RECORDED", {"text": "B (equivocating)"}, actor=HUMAN)
    run_pipe_sync(honest, pc)
    envs = fork.events_for_peer({fork.device_id: pc.vector()[fork.device_id] - 1}, "PRIVATE")
    r = pc.import_event(envs[-1], "fork")
    assert r.code == "EQUIVOCATION"
    assert any(c["kind"] == "EQUIVOCATION" for c in reconcile.open_conflicts(pc))
    assert pc.verify_integrity()["ok"]


def test_privacy_clearance_withholds_payloads_and_backfills_later(phone, pc):
    pair(phone, pc, max_privacy="INTERNAL")
    secret = phone.append("NOTE_RECORDED", {"text": "private matter"}, actor=HUMAN, privacy="PRIVATE")
    local = phone.append("NOTE_RECORDED", {"text": "device only"}, actor=HUMAN, privacy="DEVICE_LOCAL")
    run_pipe_sync(phone, pc)
    assert pc.payload_state(secret.event_id) == "WITHHELD" and pc.get(secret.event_id).payload is None
    assert pc.payload_state(local.event_id) == "WITHHELD"
    assert pc.search("private") == []
    assert pc.verify_integrity()["ok"]   # headers verify without payloads
    phone.conn.execute("UPDATE peers SET max_privacy='PRIVATE' WHERE device_id=?", (pc.device_id,))
    ri, rr = run_pipe_sync(phone, pc)
    assert secret.event_id in rr.backfilled
    assert pc.get(secret.event_id).payload == {"text": "private matter"}
    assert pc.payload_state(local.event_id) == "WITHHELD"  # DEVICE_LOCAL never leaves


def test_deletion_propagates_through_sync(paired):
    phone, pc = paired
    ev = phone.append("NOTE_RECORDED", {"text": "erase me later"}, actor=HUMAN)
    run_pipe_sync(phone, pc)
    assert pc.get(ev.event_id).payload is not None
    phone.authorize_deletion(ev.event_id, "subject asked for erasure", actor=HUMAN, operator=phone.op)
    run_pipe_sync(phone, pc)
    assert pc.payload_state(ev.event_id) == "PURGED"
    assert pc.state_digest() == phone.state_digest()


def test_offline_bundle_round_trip_replay_and_tamper(paired, tmp_path):
    phone, pc = paired
    for i in range(3):
        phone.append("NOTE_RECORDED", {"text": f"carry {i}"}, actor=HUMAN, artifact_data=[(f"raw{i}".encode(), "text/plain")])
    b = tmp_path / "phone-to-pc.fwbundle"
    info = sync.export_bundle(phone, pc.device_id, b)
    assert info["events"] >= 3
    r = sync.import_bundle(pc, b)
    assert r.complete and len(r.imported) == info["events"]
    assert pc.artifact(phone.events("NOTE_RECORDED")[0].header["artifacts"][0]) == b"raw0"
    with pytest.raises(sync.SyncError) as e:
        sync.import_bundle(pc, b)
    assert e.value.code == "REPLAY_DETECTED"
    # tampering
    doc = json.loads(b.read_text())
    doc["header"]["nonce"] = "00" * 32
    t = tmp_path / "t.fwbundle"
    t.write_text(json.dumps(doc))
    with pytest.raises(sync.SyncError) as e:
        sync.import_bundle(pc, t)
    assert e.value.code == "PEER_AUTHENTICATION_FAILED"
    # wrong recipient
    with pytest.raises(sync.SyncError) as e:
        sync.import_bundle(phone, b)
    assert e.value.code == "WRONG_RECIPIENT"


def test_real_tcp_transport(paired):
    phone, pc = paired
    phone.append("NOTE_RECORDED", {"text": "over tcp"}, actor=HUMAN)
    ready, bound, out = threading.Event(), [], {}
    t = threading.Thread(target=lambda: out.setdefault("r", sync.serve(pc, "127.0.0.1", 0, 1, 20, ready, bound)))
    t.start()
    ready.wait(5)
    rep = sync.sync_tcp(phone, "127.0.0.1", bound[0], expect=pc.device_id)
    t.join(20)
    assert rep.complete and out["r"][0].complete
    assert pc.search("tcp")
