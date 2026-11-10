"""`python -m omega` -- one CLI for both the pocket (Termux) and forge (Windows) nodes.

Node home: --home, else $OMEGA_HOME, else ~/.forgeworld-omega.
Every write names its actor explicitly (--actor human:<you>). Output is JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _home(a) -> Path:
    return Path(a.home or os.environ.get("OMEGA_HOME") or Path.home() / ".forgeworld-omega")


def _node(a):
    from omega.store import Node
    return Node.open(_home(a))


def _out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True, default=lambda o: getattr(o, "__dict__", str(o))))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="omega", description="ForgeWorld Omega node")
    ap.add_argument("--home")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("init"); p.add_argument("--label", required=True)
    p.add_argument("--profile", choices=["pocket", "forge"], default="pocket")
    sp.add_parser("offer")
    sp.add_parser("sas")
    p = sp.add_parser("pair"); p.add_argument("--offer", required=True)
    p.add_argument("--sas", help="omit to display the SAS; then re-run with the digits both screens show")
    p.add_argument("--actor", required=True); p.add_argument("--max-privacy", default="PRIVATE")
    p.add_argument("--my-offer", required=True, help="the offer this device printed (from `omega offer`)")
    p = sp.add_parser("revoke"); p.add_argument("--peer", required=True); p.add_argument("--actor", required=True)

    p = sp.add_parser("contact-add"); p.add_argument("--name", required=True); p.add_argument("--primary", required=True)
    p.add_argument("--alias", action="append", default=[]); p.add_argument("--actor", required=True)
    p = sp.add_parser("message"); p.add_argument("--contact", required=True)
    p.add_argument("--direction", choices=["IN", "OUT"], required=True); p.add_argument("--text", required=True)
    p.add_argument("--at", required=True, help="UTC YYYY-MM-DDTHH:MM:SSZ"); p.add_argument("--source", required=True)
    p.add_argument("--channel", default="sms"); p.add_argument("--actor", required=True)
    p = sp.add_parser("fact"); p.add_argument("--contact", required=True); p.add_argument("--attribute", required=True)
    p.add_argument("--value", required=True); p.add_argument("--actor", required=True)
    p = sp.add_parser("commitment"); p.add_argument("--contact", required=True); p.add_argument("--text", required=True)
    p.add_argument("--owed-by", choices=["US", "THEM"], required=True); p.add_argument("--due"); p.add_argument("--actor", required=True)
    p = sp.add_parser("context"); p.add_argument("--contact", required=True)
    p = sp.add_parser("check-draft"); p.add_argument("--contact", required=True); p.add_argument("--text", required=True)
    p = sp.add_parser("draft"); p.add_argument("--contact", required=True); p.add_argument("--intent", default="follow_up")
    p.add_argument("--sender", default=""); p.add_argument("--model", help="optional local Ollama model")
    p = sp.add_parser("search"); p.add_argument("query"); p.add_argument("--contact")

    p = sp.add_parser("deal"); p.add_argument("--deal", required=True); p.add_argument("--stage", required=True)
    p.add_argument("--summary", required=True); p.add_argument("--source", required=True); p.add_argument("--actor", required=True)
    p.add_argument("--amount-minor", type=int); p.add_argument("--currency"); p.add_argument("--reference")
    p.add_argument("--due"); p.add_argument("--document", help="path of the signed document (written agreement)")
    p = sp.add_parser("verify-payment"); p.add_argument("--deal", required=True); p.add_argument("--reference", required=True)
    p.add_argument("--amount-minor", type=int, required=True); p.add_argument("--currency", required=True)
    p.add_argument("--settlement-source", choices=["bank_statement", "processor_record"], required=True)
    p.add_argument("--record", required=True, help="path of the settlement record"); p.add_argument("--actor", required=True)
    p = sp.add_parser("deal-state"); p.add_argument("--deal", required=True)

    p = sp.add_parser("task-queue"); p.add_argument("--action", required=True); p.add_argument("--args", default="{}")
    p.add_argument("--external", action="store_true"); p.add_argument("--actor", required=True)
    p = sp.add_parser("task-authorize"); p.add_argument("--task", required=True); p.add_argument("--actor", required=True)
    sp.add_parser("task-list"); sp.add_parser("task-run"); sp.add_parser("task-recover")

    p = sp.add_parser("serve"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=47470)
    p.add_argument("--sessions", type=int, default=1)
    p = sp.add_parser("sync"); p.add_argument("--host", required=True); p.add_argument("--port", type=int, default=47470)
    p.add_argument("--peer")
    p = sp.add_parser("bundle-export"); p.add_argument("--peer", required=True); p.add_argument("--out", required=True)
    p.add_argument("--full", action="store_true", help="ignore the last known peer vector")
    p = sp.add_parser("bundle-import"); p.add_argument("path")
    p = sp.add_parser("announce"); p.add_argument("--port", type=int, default=47470)
    p = sp.add_parser("discover"); p.add_argument("--timeout", type=float, default=10)

    sp.add_parser("conflicts")
    p = sp.add_parser("resolve"); p.add_argument("--key", required=True); p.add_argument("--value", required=True)
    p.add_argument("--actor", required=True)
    p = sp.add_parser("delete"); p.add_argument("--event", required=True); p.add_argument("--reason", required=True)
    p.add_argument("--actor", required=True)
    p = sp.add_parser("retention"); p.add_argument("--event-type", required=True); p.add_argument("--days", type=int, required=True)
    p.add_argument("--actor", required=True)
    sp.add_parser("apply-retention")
    p = sp.add_parser("diag"); p.add_argument("--out"); p.add_argument("--probe-ollama", action="store_true")
    sp.add_parser("verify")
    p = sp.add_parser("backup"); p.add_argument("--out", required=True)
    p = sp.add_parser("receipts"); p.add_argument("--last", type=int, default=10)

    p = sp.add_parser("benchmark"); p.add_argument("--model", action="append", required=True)
    p = sp.add_parser("route"); p.add_argument("--task-class", required=True); p.add_argument("--max-latency-ms", type=int, default=30000)
    p = sp.add_parser("analyze-repo"); p.add_argument("--path", default=".")

    a = ap.parse_args(argv)
    if a.cmd == "init":
        from omega.store import Node
        n = Node.init(_home(a), a.label, a.profile)
        return _out({"device_id": n.device_id, "home": str(_home(a)), "profile": a.profile})
    n = _node(a)
    try:
        return _dispatch(a, n)
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(json.dumps({"error": code, "detail": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
    finally:
        n.close()


def _dispatch(a, n):
    from omega import reconcile, receipts, sync
    from omega.events import event_id_for
    from omega.identity import parse_offer, short_auth_string
    from omega.relationship import RelationshipMemory
    from omega.commercial import CommercialLedger
    from omega.tasks import TaskQueue
    rm = RelationshipMemory(n)
    c = a.cmd
    if c == "offer":
        return print(n.identity.pairing_offer(n.info["label"]))
    if c == "sas":
        raise SystemExit("run `pair --offer <theirs> --my-offer <yours> --sas <digits>`; it prints the SAS it computed")
    if c == "pair":
        other, mine = parse_offer(a.offer), parse_offer(a.my_offer)
        if not a.sas:
            print(f"SAS: {short_auth_string(other, mine)}  -- confirm the other device shows the same digits, "
                  "then re-run with --sas <digits>")
            raise SystemExit(3)
        ev = n.add_peer(other, mine, a.sas, actor=a.actor, max_privacy=a.max_privacy)
        return _out({"paired": other["device_id"], "label": other["label"], "event": event_id_for(ev.header)})
    if c == "revoke":
        return _out({"event": event_id_for(n.revoke_peer(a.peer, actor=a.actor).header)})
    if c == "contact-add":
        return _out({"contact_id": rm.add_contact(a.name, primary=a.primary, aliases=a.alias, actor=a.actor)})
    if c == "message":
        r = rm.record_message(a.contact, direction=a.direction, text=a.text, sent_at=a.at, source_ref=a.source,
                              actor=a.actor, channel=a.channel)
        return _out({"status": r["status"], "event": event_id_for(r["event"].header), "novelty": r["novelty"],
                     "facts": [f.payload for f in r.get("facts", [])]})
    if c == "fact":
        ev = rm.assert_fact(a.contact, a.attribute, a.value, basis="OPERATOR", actor=a.actor)
        return _out({"event": event_id_for(ev.header) if ev else None, "note": None if ev else "already known"})
    if c == "commitment":
        return _out({"commitment_id": rm.add_commitment(a.contact, a.text, owed_by=a.owed_by, due=a.due, actor=a.actor)})
    if c == "context":
        return _out(rm.context(a.contact))
    if c == "check-draft":
        return _out(rm.check_draft(a.contact, a.text))
    if c == "draft":
        gen = None
        if a.model:
            from omega.forge import OllamaClient
            gen = OllamaClient().drafter(a.model)
        return _out(rm.compose(a.contact, a.intent, sender=a.sender, generator=gen))
    if c == "search":
        ids = n.search(a.query, entity=f"contact:{a.contact}" if a.contact else None)
        return _out([{"event_id": i, "type": n.get(i).header["event_type"]} for i in ids])
    if c == "deal":
        doc = Path(a.document).read_bytes() if a.document else None
        ev = CommercialLedger(n).record(a.deal, a.stage, a.summary, actor=a.actor, source_ref=a.source,
                                        amount_minor=a.amount_minor, currency=a.currency, reference=a.reference,
                                        due=a.due, document=doc)
        return _out({"event": event_id_for(ev.header)})
    if c == "verify-payment":
        ev = CommercialLedger(n).verify_payment(a.deal, reference=a.reference, amount_minor=a.amount_minor,
                                                currency=a.currency, settlement_source=a.settlement_source,
                                                settlement_record=Path(a.record).read_bytes(), actor=a.actor)
        return _out({"event": event_id_for(ev.header)})
    if c == "deal-state":
        return _out(CommercialLedger(n).deal_state(a.deal))
    q = TaskQueue(n, _executors())
    if c == "task-queue":
        return _out({"task_id": q.queue(a.action, json.loads(a.args), actor=a.actor, external_effect=a.external)})
    if c == "task-authorize":
        return _out({"event": event_id_for(q.authorize(a.task, actor=a.actor).header)})
    if c == "task-list":
        return _out(q.tasks())
    if c == "task-run":
        return _out(q.run_once())
    if c == "task-recover":
        return _out(q.recover())
    if c == "serve":
        return _out(sync.serve(n, a.host, a.port, a.sessions))
    if c == "sync":
        return _out(sync.sync_tcp(n, a.host, a.port, expect=a.peer))
    if c == "bundle-export":
        return _out(sync.export_bundle(n, a.peer, a.out, since={} if a.full else None))
    if c == "bundle-import":
        return _out(sync.import_bundle(n, a.path))
    if c == "announce":
        from omega import discovery
        discovery.announce(n, a.port)
        return _out({"announced": n.device_id})
    if c == "discover":
        from omega import discovery
        return _out(discovery.listen(n, a.timeout))
    if c == "conflicts":
        reconcile.reconcile_all(n)
        return _out(reconcile.open_conflicts(n))
    if c == "resolve":
        return _out({"event": event_id_for(reconcile.resolve_conflict(n, a.key, a.value, actor=a.actor).header)})
    if c == "delete":
        return _out({"event": event_id_for(n.authorize_deletion(a.event, a.reason, actor=a.actor).header)})
    if c == "retention":
        ev = n.append("RETENTION_POLICY", {"event_type": a.event_type, "max_age_days": a.days}, actor=a.actor,
                      privacy="INTERNAL")
        return _out({"event": event_id_for(ev.header)})
    if c == "apply-retention":
        return _out({"purged": n.apply_retention()})
    if c == "diag":
        from omega import diagnostics
        r = diagnostics.report(n, probe_ollama=a.probe_ollama)
        if a.out:
            Path(a.out).write_text(json.dumps(r, indent=2, sort_keys=True))
        return _out(r)
    if c == "verify":
        r = n.verify_integrity()
        _out(r)
        raise SystemExit(0 if r["ok"] else 2)
    if c == "backup":
        return _out({"backup": str(n.backup(Path(a.out)))})
    if c == "receipts":
        return _out(receipts.all_receipts(n)[-a.last:])
    if c in ("benchmark", "route", "analyze-repo"):
        from omega import forge
        if c == "benchmark":
            return _out([e.payload for e in forge.run_benchmark(n, forge.OllamaClient(), a.model)])
        if c == "route":
            cl = forge.OllamaClient(timeout=5)
            avail = cl.models() if cl.available() else []
            return _out(forge.ModelRouter(n).select(a.task_class, max_latency_ms=a.max_latency_ms, available=avail))
        return _out(forge.analyze_repository(Path(a.path)))
    raise SystemExit(f"unknown command {c}")


def _executors():
    """Built-in executors. Only internal, local actions ship by default; an
    operator adds external ones (send, pay, post) deliberately."""
    from omega.tasks import Executor
    return {"noop": Executor(lambda args: "ok", external=False)}


if __name__ == "__main__":
    main()
