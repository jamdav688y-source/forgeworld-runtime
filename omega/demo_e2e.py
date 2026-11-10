"""FW-SCS-001 final acceptance scenario, executable and reproducible.

    python -m omega.demo_e2e --workdir <empty dir> [--samples docs/omega/samples]

1. Phone and PC are paired once (human-confirmed SAS), then the PC goes away.
2. With every socket blocked, the phone captures a conversation fact with its
   source (message text + raw SMS artifact) and extracts the answer.
3. Still offline, a naive draft that re-asks the answered question is blocked,
   and the phone's own draft advances to the next unanswered question; the
   operator sends it and the contact answers (all captured offline).
4. The PC becomes available: the nodes authenticate and sync over real TCP.
5. The PC verifies the imported evidence (ids, signatures, chain, provenance
   back to the raw artifact) and reconstructs the identical contact context.
6. A request to send a reply is held until a human authorizes it ON THE PC;
   then the PC composes a contextually advanced reply (acknowledges the newest
   answer, asks the next open question, re-asks nothing) and "sends" it to a
   local outbox (no network).
7. The result syncs back; both nodes verify; receipts exist for every
   material transition.
"""
from __future__ import annotations

import argparse
import itertools
import json
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from omega import receipts, sync
from omega.canonical import sha256_hex
from omega.events import event_id_for
from omega.identity import parse_offer, short_auth_string
from omega.relationship import RelationshipMemory
from omega.store import Node
from omega.tasks import Executor, TaskQueue

HUMAN = "human:operator"
DEMO_PASSPHRASE = "demo passphrase - never reuse"


def _clock(start):
    c = itertools.count()
    return lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + next(c)))


@contextmanager
def no_network():
    """Every socket creation fails: proves the phone needs no network."""
    real = socket.socket

    class Blocked(real):
        def __init__(self, *a, **k):
            raise OSError("network disabled for offline test")
    socket.socket = Blocked
    try:
        yield
    finally:
        socket.socket = real


def run(workdir) -> dict:
    workdir = Path(workdir)
    phone = Node.init(workdir / "phone", "pocket-phone", "pocket")
    pc = Node.init(workdir / "pc", "forge-pc", "forge")
    phone.clock, pc.clock = _clock(1793534400), _clock(1793620800)
    # each device registers its operator key (passphrase-protected); the demo
    # passphrase stands in for the one a person types at the prompt
    phone.create_operator("operator", DEMO_PASSPHRASE)
    pc.create_operator("operator", DEMO_PASSPHRASE)
    op_phone, op_pc = phone.unlock_operator(DEMO_PASSPHRASE), pc.unlock_operator(DEMO_PASSPHRASE)
    oa = parse_offer(phone.pairing_offer())
    ob = parse_offer(pc.pairing_offer())
    sas = short_auth_string(oa, ob)
    phone.add_peer(ob, oa, sas, actor=HUMAN, operator=op_phone)
    pc.add_peer(oa, ob, sas, actor=HUMAN, operator=op_pc)
    out = {"phone": phone.device_id, "pc": pc.device_id, "sas": sas}

    # ---- 2/3: phone alone, offline -------------------------------------
    with no_network():
        rm = RelationshipMemory(phone)
        cid = rm.add_contact("Dana Reyes", primary="sms:+15550100", aliases=["Dee"], actor=HUMAN,
                             channels=[{"kind": "sms", "address": "+15550100"}])
        rm.record_message(cid, direction="OUT", sent_at="2026-11-01T10:00:00Z", source_ref="sms:thread-77/msg-1",
                          actor=HUMAN, text="Hi Dana, great to meet you at the expo. What budget do you have in mind?")
        raw = b"SMS from +15550100 2026-11-01T10:42:00Z: Around $5,000 for phase one. Text is best, please don't call me."
        cap = rm.record_message(cid, direction="IN", sent_at="2026-11-01T10:42:00Z", source_ref="sms:thread-77/msg-2",
                                actor="tool:sms-import", raw=raw,
                                text="Around $5,000 for phase one. Text is best, please don't call me.")
        out["captured_message"] = event_id_for(cap["event"].header)
        out["extracted_facts"] = sorted((f.payload["attribute"], f.payload["value"]) for f in cap["facts"])
        naive = rm.check_draft(cid, "Hi Dana, what's your budget? Happy to call you to discuss.")
        out["naive_draft_blocked"] = sorted({f["code"] for f in naive if f["severity"] == "BLOCK"})
        d1 = rm.compose(cid, "discovery", sender="J.")
        out["phone_draft"] = d1["text"]
        out["phone_draft_next_question"] = d1["next_question"]
        # the operator sends that draft by hand; Dana answers the new question
        rm.record_message(cid, direction="OUT", sent_at="2026-11-01T11:05:00Z", source_ref="sms:thread-77/msg-3",
                          actor=HUMAN, text=d1["text"])
        rm.record_message(cid, direction="IN", sent_at="2026-11-01T11:30:00Z", source_ref="sms:thread-77/msg-4",
                          actor="tool:sms-import",
                          text="Cutting our customer onboarding time in half. That would be a big win for us.")
        out["phone_context_digest"] = rm.context_digest(cid)
        out["phone_offline_integrity"] = phone.verify_integrity()["ok"]

    # ---- 4: PC becomes available, authenticated TCP sync ----------------
    ready, bound, res = threading.Event(), [], {}
    t = threading.Thread(target=lambda: res.setdefault("pc", sync.serve(pc, "127.0.0.1", 0, 1, 30, ready, bound)))
    t.start()
    ready.wait(10)
    rep = sync.sync_tcp(phone, "127.0.0.1", bound[0], expect=pc.device_id)
    t.join(30)
    out["sync_complete"] = rep.complete and res["pc"][0].complete
    out["pc_imported"] = len(res["pc"][0].imported)

    # ---- 5: PC verifies evidence and reconstructs state ------------------
    out["pc_integrity"] = pc.verify_integrity()["ok"]
    rpc = RelationshipMemory(pc)
    ctx = rpc.context(cid)
    budget = ctx["facts"]["budget"]
    msg = pc.get(out["captured_message"])
    out["pc_provenance_chain"] = {
        "fact_value": budget["value"],
        "fact_rests_on_message": out["captured_message"] in budget["evidence"],
        "message_source": msg.header["provenance"][0]["ref"],
        "raw_artifact_matches": pc.artifact(msg.header["artifacts"][0]) == raw
        and msg.header["artifacts"][0] == sha256_hex(raw),
        "message_signed_by_phone": msg.header["device_id"] == phone.device_id,
    }
    out["pc_known_facts"] = sorted(a for a, f in ctx["facts"].items() if f["status"] == "RESOLVED")
    out["pc_context_digest"] = rpc.context_digest(cid)
    out["same_context"] = out["pc_context_digest"] == out["phone_context_digest"]

    # ---- 6: authorized request produces an advanced response -------------
    outbox = []

    def send_reply(args):
        d = RelationshipMemory(pc).compose(args["contact_id"], args["intent"], sender="J.")
        if any(f["severity"] == "BLOCK" for f in d["findings"]):
            raise RuntimeError(f"draft blocked: {d['findings']}")
        outbox.append({"to": args["contact_id"], "text": d["text"], "draft_event": d["event_id"]})
        return f"queued to local outbox: {d['event_id']}"

    q = TaskQueue(pc, {"send_reply": Executor(send_reply, external=True)})
    tid = q.queue("send_reply", {"contact_id": cid, "intent": "discovery"}, actor="model:assistant",
                  external_effect=True, links=[f"contact:{cid}"])
    out["before_authorization"] = dict(q.run_once())[tid]
    out["outbox_before_authorization"] = len(outbox)
    # an agent that can run code but does not know the passphrase cannot authorize
    from omega.store import StoreError
    try:
        q.authorize(tid, actor=HUMAN, note="agent pretending to be the operator")
        out["forged_authorization"] = "ACCEPTED"
    except StoreError as exc:
        out["forged_authorization"] = exc.code
    try:
        pc.unlock_operator("guessed passphrase")
        out["wrong_passphrase"] = "UNLOCKED"
    except PermissionError as exc:
        out["wrong_passphrase"] = getattr(exc, "code", "REFUSED")
    out["after_forgery_attempts"] = dict(q.run_once())[tid]
    q.authorize(tid, actor=HUMAN, note="send the discovery follow-up", operator=op_pc)
    out["after_authorization"] = dict(q.run_once())[tid]
    out["sent_reply"] = outbox[0]["text"] if outbox else None
    out["sent_reply_findings"] = sorted({f["code"] for f in RelationshipMemory(pc).check_draft(cid, out["sent_reply"] or "")
                                         if f["severity"] == "BLOCK"})

    # ---- 7: result flows back, both verify -------------------------------
    ready, bound, res = threading.Event(), [], {}
    t = threading.Thread(target=lambda: res.setdefault("phone", sync.serve(phone, "127.0.0.1", 0, 1, 30, ready, bound)))
    t.start()
    ready.wait(10)
    rep2 = sync.sync_tcp(pc, "127.0.0.1", bound[0], expect=phone.device_id)
    t.join(30)
    out["sync_back_complete"] = rep2.complete
    out["vectors_equal"] = phone.vector() == pc.vector()
    out["state_digests_equal"] = phone.state_digest() == pc.state_digest()
    out["final_integrity"] = phone.verify_integrity()["ok"] and pc.verify_integrity()["ok"]
    out["phone_receipt_types"] = sorted({r["type"] for r in receipts.all_receipts(phone)})
    out["pc_receipt_types"] = sorted({r["type"] for r in receipts.all_receipts(pc)})
    out["_nodes"] = (phone, pc)
    return out


def write_samples(out: dict, dest) -> None:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    phone, pc = out["_nodes"]
    public = {k: v for k, v in out.items() if not k.startswith("_")}
    (dest / "e2e_result.json").write_text(json.dumps(public, indent=2, sort_keys=True))
    (dest / "receipts_phone.json").write_text(json.dumps(receipts.all_receipts(phone), indent=2, sort_keys=True))
    (dest / "receipts_pc.json").write_text(json.dumps(receipts.all_receipts(pc), indent=2, sort_keys=True))
    ev = phone.get(public["captured_message"])
    (dest / "event_sample.json").write_text(json.dumps(ev.envelope(), indent=2, sort_keys=True))
    from omega import diagnostics
    (dest / "diagnostics_pc.json").write_text(json.dumps(diagnostics.report(pc), indent=2, sort_keys=True))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--samples")
    a = ap.parse_args(argv)
    out = run(a.workdir)
    if a.samples:
        write_samples(out, a.samples)
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("_")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
