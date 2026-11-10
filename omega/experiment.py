"""First physical phone <-> PC experiment (directive 3, section 8), as
recorded, signed steps.

    PHONE OFFLINE -> LOCAL MEMORY -> RESTART -> CONTINUITY GATE ->
    PC AVAILABLE -> AUTHENTICATED SYNC -> IDEMPOTENT RE-SYNC -> VERIFIED RECALL

Each step runs as its own process and appends a record to
<dir>/experiment-<role>.json. `report` merges the phone and PC files into one
signed verdict. Every record holds the facts the step observed: process id,
platform, network reachability, event ids, hashes, vectors, digests.
Nothing is inferred, and only synthetic data is used.

Phone (Termux):
    python -m omega.experiment init     --dir D --role phone --label phone   # asks for a passphrase
    python -m omega.experiment capture  --dir D            # with Wi-Fi AND mobile data OFF
    (close Termux completely, reopen)
    python -m omega.experiment recall   --dir D            # new process: persistence + continuity gate
PC (PowerShell):
    py -m omega.experiment init --dir D --role pc --label pc
    (pair both nodes: omega pair ..., see PHYSICAL_PROOF_PROTOCOL.md)
    py -m omega.experiment serve --dir D --host <PC LAN IP>        # accepts 2 sessions
Phone (Wi-Fi on):
    python -m omega.experiment sync --dir D --host <PC LAN IP>     # syncs twice: 2nd must move 0
PC:
    py -m omega.experiment verify --dir D --phone-record <phone experiment file>
Either:
    python -m omega.experiment report --phone <file> --pc <file> --out verdict.json
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from omega import proof  # noqa: E402
from omega.events import event_id_for  # noqa: E402

CONTACT = {"name": "Synthetic Contact", "primary": "sms:+10000000001"}
QUESTION = "Hi Synthetic, what budget do you have in mind for the pilot?"
ANSWER = "Around $2,500 to start."
REPEAT_DRAFT = "Hi Synthetic, how much budget do you have for this?"


def _home(d) -> Path:
    return Path(d) / "node"


def _record_path(d, role) -> Path:
    return Path(d) / f"experiment-{role}.json"


def _role(d) -> str:
    return json.loads((Path(d) / "role.json").read_text())["role"]


def _network_reachable() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        return True
    except OSError:
        return False


def _append(d, step: str, ok: bool, facts: dict):
    role = _role(d)
    p = _record_path(d, role)
    doc = json.loads(p.read_text()) if p.exists() else {"schema": "fw.omega.experiment/1", "role": role, "steps": []}
    doc["steps"].append({"step": step, "ok": bool(ok), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "pid": os.getpid(), "platform": proof._platform()["platform"], "facts": facts})
    p.write_text(json.dumps(doc, indent=2, sort_keys=True))
    print(json.dumps({"step": step, "ok": bool(ok), **facts}, indent=2, sort_keys=True))
    return ok


def _passphrase(prompt):
    if os.environ.get("OMEGA_EXPERIMENT_PASSPHRASE_STDIN") == "1":
        return sys.stdin.readline().rstrip("\n")
    import getpass
    return getpass.getpass(prompt)


def cmd_init(a):
    from omega.store import Node
    Path(a.dir).mkdir(parents=True, exist_ok=True)
    (Path(a.dir) / "role.json").write_text(json.dumps({"role": a.role}))
    n = Node.init(_home(a.dir), a.label, "pocket" if a.role == "phone" else "forge")
    s = n.create_operator(a.operator, _passphrase("New operator passphrase (10+ chars): "))
    ok = _append(a.dir, "init", True, {"device_id": n.device_id, "operator_id": s.operator_id,
                                       "home": str(_home(a.dir)), "platform_full": proof._platform()})
    n.close()
    return ok


def cmd_capture(a):
    from omega.relationship import RelationshipMemory
    from omega.store import Node
    online = _network_reachable()
    n = Node.open(_home(a.dir))
    rm = RelationshipMemory(n)
    cid = rm.add_contact(CONTACT["name"], primary=CONTACT["primary"], actor="human:" + a.operator)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    q = rm.record_message(cid, direction="OUT", text=QUESTION, sent_at=now, source_ref="experiment:sms/1",
                          actor="human:" + a.operator)
    r = rm.record_message(cid, direction="IN", text=ANSWER, sent_at=now, source_ref="experiment:sms/2",
                          actor="tool:experiment", raw=ANSWER.encode())
    ev = r["event"]
    facts = {"network_reachable_during_capture": online, "contact_id": cid,
             "question_event": event_id_for(q["event"].header), "answer_event": event_id_for(ev.header),
             "answer_ts": ev.header["ts"], "answer_source": ev.header["provenance"][0]["ref"],
             "answer_payload_hash": ev.header["payload_hash"], "answer_artifact_sha256": ev.header["artifacts"][0],
             "extracted": [(f.payload["attribute"], f.payload["value"]) for f in r["facts"]],
             "vector": n.vector()}
    ok = not online and any(x[0] == "budget" for x in facts["extracted"])
    n.close()
    if online:
        print("NOTE: the network was reachable. Turn Wi-Fi AND mobile data off and run capture again "
              "in a fresh --dir for an offline result.", file=sys.stderr)
    return _append(a.dir, "capture_offline", ok, facts)


def _last(d, step):
    p = _record_path(d, _role(d))
    for s in reversed(json.loads(p.read_text())["steps"]):
        if s["step"] == step:
            return s
    raise SystemExit(f"run `{step}` first")


def cmd_recall(a):
    from omega.relationship import RelationshipMemory
    from omega.store import Node
    cap = _last(a.dir, "capture_offline")
    n = Node.open(_home(a.dir))
    ev = n.get(cap["facts"]["answer_event"])
    integ = n.verify_integrity()
    rm = RelationshipMemory(n)
    cid = cap["facts"]["contact_id"]
    findings = rm.check_draft(cid, REPEAT_DRAFT)
    gate = sorted({f["code"] for f in findings if f["severity"] == "BLOCK"})
    facts = {"new_process": os.getpid() != cap["pid"], "capture_pid": cap["pid"],
             "event_found": ev is not None,
             "payload_hash_matches": bool(ev) and ev.header["payload_hash"] == cap["facts"]["answer_payload_hash"],
             "raw_artifact_matches": bool(ev) and n.artifact(cap["facts"]["answer_artifact_sha256"]) == ANSWER.encode(),
             "integrity_ok": integ["ok"], "recalled_budget": rm.context(cid)["facts"].get("budget", {}).get("value"),
             "repeat_draft": REPEAT_DRAFT, "continuity_gate_blocks": gate,
             "context_digest": rm.context_digest(cid)}
    ok = (facts["new_process"] and facts["event_found"] and facts["payload_hash_matches"]
          and facts["raw_artifact_matches"] and integ["ok"] and "REPEATED_QUESTION" in gate)
    n.close()
    return _append(a.dir, "recall_after_restart", ok, facts)


def cmd_serve(a):
    from omega import sync
    from omega.store import Node
    n = Node.open(_home(a.dir))
    print(f"PC device_id: {n.device_id}  listening on {a.host}:{a.port} for 2 sessions...", file=sys.stderr)
    reps = sync.serve(n, a.host, a.port, sessions=2, timeout=a.timeout)
    out = []
    for r in reps:
        out.append({"error": f"{type(r).__name__}: {r}"} if isinstance(r, Exception) else
                   {"complete": r.complete, "peer": r.peer, "imported": len(r.imported), "sent": r.sent,
                    "problems": [list(map(str, p)) for p in r.problems]})
    ok = len(out) == 2 and all(o.get("complete") for o in out)
    facts = {"host": a.host, "port": a.port, "sessions": out, "vector": n.vector(), "integrity_ok": n.verify_integrity()["ok"]}
    n.close()
    return _append(a.dir, "serve", ok, facts)


def cmd_sync(a):
    from omega import sync
    from omega.store import Node
    n = Node.open(_home(a.dir))
    peers = [p for p in n.peers() if not p["revoked"]]
    if len(peers) != 1:
        raise SystemExit("pair exactly one PC first (omega pair ...)")
    runs = []
    for i in range(2):
        r = sync.sync_tcp(n, a.host, a.port, expect=peers[0]["device_id"], timeout=a.timeout)
        runs.append({"complete": r.complete, "sent": r.sent, "imported": len(r.imported),
                     "duplicates": r.duplicates, "problems": [list(map(str, p)) for p in r.problems]})
        time.sleep(1)
    facts = {"pc_device_id": peers[0]["device_id"], "host": a.host, "first": runs[0], "second": runs[1],
             "vector": n.vector(), "integrity_ok": n.verify_integrity()["ok"]}
    ok = runs[0]["complete"] and runs[0]["sent"] > 0 and runs[1]["complete"] \
        and runs[1]["sent"] == 0 and runs[1]["imported"] == 0 and facts["integrity_ok"]
    n.close()
    return _append(a.dir, "lan_sync_twice", ok, facts)


def cmd_verify(a):
    from omega.relationship import RelationshipMemory
    from omega.store import Node
    phone = json.loads(Path(a.phone_record).read_text())
    cap = next(s for s in phone["steps"] if s["step"] == "capture_offline")
    rec = next(s for s in reversed(phone["steps"]) if s["step"] == "recall_after_restart")
    phone_id = next(s for s in phone["steps"] if s["step"] == "init")["facts"]["device_id"]
    n = Node.open(_home(a.dir))
    ev = n.get(cap["facts"]["answer_event"])
    integ = n.verify_integrity()
    rm = RelationshipMemory(n)
    cid = cap["facts"]["contact_id"]
    facts = {"event_present": ev is not None, "signed_by_phone": bool(ev) and ev.header["device_id"] == phone_id,
             "payload_hash_matches": bool(ev) and ev.header["payload_hash"] == cap["facts"]["answer_payload_hash"],
             "raw_artifact_matches": n.artifact(cap["facts"]["answer_artifact_sha256"]) == ANSWER.encode(),
             "integrity_ok": integ["ok"], "recalled_budget": rm.context(cid)["facts"].get("budget", {}).get("value"),
             "context_digest": rm.context_digest(cid), "phone_context_digest_at_recall": rec["facts"]["context_digest"],
             "continuity_gate_blocks": sorted({f["code"] for f in rm.check_draft(cid, REPEAT_DRAFT)
                                               if f["severity"] == "BLOCK"})}
    facts["same_context_as_phone"] = facts["context_digest"] == facts["phone_context_digest_at_recall"]
    ok = all(facts[k] for k in ("event_present", "signed_by_phone", "payload_hash_matches", "raw_artifact_matches",
                                "integrity_ok", "same_context_as_phone")) and "REPEATED_QUESTION" in facts["continuity_gate_blocks"]
    n.close()
    return _append(a.dir, "pc_verify", ok, facts)


REQUIRED = {"phone": ["init", "capture_offline", "recall_after_restart", "lan_sync_twice"],
            "pc": ["init", "serve", "pc_verify"]}


def cmd_report(a):
    docs = {"phone": json.loads(Path(a.phone).read_text()), "pc": json.loads(Path(a.pc).read_text())}
    verdict = {}
    for role, steps in REQUIRED.items():
        have = {s["step"]: s for s in docs[role]["steps"]}
        for st in steps:
            verdict[f"{role}:{st}"] = bool(have.get(st, {}).get("ok"))
    plat = {r: next(s for s in d["steps"] if s["step"] == "init")["facts"]["platform_full"] for r, d in docs.items()}
    doc = {"schema": "fw.omega.experiment-report/1", "device": "phone + pc (operator's statement in the step records)",
           "platform": {"phone": plat["phone"], "pc": plat["pc"], "platform": f"{plat['phone']['platform']} | {plat['pc']['platform']}"},
           "sources": proof._sources(),
           "checks": {k: {"ok": v} for k, v in verdict.items()},
           "phone_is_android": plat["phone"]["android"] or plat["phone"]["termux"],
           "pc_is_windows": plat["pc"]["windows"], "records": docs,
           "all_ok": all(verdict.values()) and (plat["phone"]["android"] or plat["phone"]["termux"]) and plat["pc"]["windows"]}
    signed = proof._sign(doc, Path(a.out))
    print(json.dumps({"proof_id": signed["proof_id"], "all_ok": doc["all_ok"], "steps": verdict,
                      "phone_is_android": doc["phone_is_android"], "pc_is_windows": doc["pc_is_windows"]}, indent=2))
    return doc["all_ok"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="omega.experiment")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init"); p.add_argument("--dir", required=True); p.add_argument("--role", choices=["phone", "pc"], required=True)
    p.add_argument("--label", required=True); p.add_argument("--operator", default="owner")
    for name in ("capture", "recall"):
        p = sp.add_parser(name); p.add_argument("--dir", required=True); p.add_argument("--operator", default="owner")
    for name in ("serve", "sync"):
        p = sp.add_parser(name); p.add_argument("--dir", required=True); p.add_argument("--host", required=True)
        p.add_argument("--port", type=int, default=47470); p.add_argument("--timeout", type=float, default=600)
    p = sp.add_parser("verify"); p.add_argument("--dir", required=True); p.add_argument("--phone-record", required=True)
    p = sp.add_parser("report"); p.add_argument("--phone", required=True); p.add_argument("--pc", required=True)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ok = {"init": cmd_init, "capture": cmd_capture, "recall": cmd_recall, "serve": cmd_serve, "sync": cmd_sync,
          "verify": cmd_verify, "report": cmd_report}[a.cmd](a)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
