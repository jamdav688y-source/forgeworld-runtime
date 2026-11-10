"""Deterministic reconciliation of mutable state + explicit conflicts (Stage E).

Events never conflict (they are immutable and content addressed). STATE
does: two devices can assert different values for the same key without
having seen each other's assertion. Keys:

    fact|<subject>|<attribute>        FACT_ASSERTED
    commitment|<commitment_id>|status COMMITMENT_STATUS
    contact|<contact_id>|display_name CONTACT_ASSERTED (with display_name)
    <any key>                         CONFLICT_RESOLVED (human)

Rule (independent of import order and of clocks):
  1. assertions(key) = events for the key whose payload is present
  2. heads = assertions not in the causal ancestry (prev/parents/supersedes/
     corrects) of another assertion of the same key
  3. one head, or all heads agree  -> RESOLVED with that value
     heads disagree                -> CONFLICTED, value None, and an explicit
                                      conflict row + CONFLICT_DETECTED receipt
  No last-writer-wins, no clock comparison, no silent merge. A human
  resolves by writing CONFLICT_RESOLVED whose parents are exactly the
  conflicting heads; it then dominates them and becomes the single head.
Local writers add the current heads of a key as parents (they have seen
them), so sequential edits on one device or after a sync never conflict.
"""
from __future__ import annotations

import json
from typing import Optional

from omega import receipts
from omega.canonical import digest
from omega.events import event_id_for

KEYED_TYPES = ("FACT_ASSERTED", "COMMITMENT_STATUS", "CONTACT_ASSERTED", "CONFLICT_RESOLVED")


def key_of(ev) -> Optional[str]:
    p, et = ev.payload, ev.header["event_type"]
    if p is None:
        return None
    if et == "FACT_ASSERTED":
        return f"fact|{p['subject']}|{p['attribute']}"
    if et == "COMMITMENT_STATUS":
        return f"commitment|{p['commitment_id']}|status"
    if et == "CONTACT_ASSERTED" and p.get("display_name"):
        return f"contact|{p['contact_id']}|display_name"
    if et == "CONFLICT_RESOLVED":
        return p["key"]
    return None


def value_of(ev) -> str:
    p, et = ev.payload, ev.header["event_type"]
    return {"FACT_ASSERTED": lambda: p["value"], "COMMITMENT_STATUS": lambda: p["status"],
            "CONTACT_ASSERTED": lambda: p["display_name"], "CONFLICT_RESOLVED": lambda: p["value"]}[et]()


def assertions_by_key(node, prefix: str = "") -> dict:
    out = {}
    for et in KEYED_TYPES:
        for ev in node.events(et):
            k = key_of(ev)
            if k is not None and k.startswith(prefix):
                out.setdefault(k, []).append(ev)
    return out


def _heads(node, evs) -> list:
    ids = {event_id_for(e.header): e for e in evs}
    dominated = set()
    for eid in ids:
        anc = node.ancestors(eid)
        dominated |= (anc & set(ids))
    return sorted((ids[i] for i in ids if i not in dominated), key=lambda e: event_id_for(e.header))


def resolve(node, key: str, evs: Optional[list] = None) -> dict:
    if evs is None:
        evs = assertions_by_key(node).get(key, [])
    if not evs:
        return {"key": key, "status": "EMPTY", "value": None, "heads": [], "evidence": []}
    heads = _heads(node, evs)
    values = sorted({value_of(h) for h in heads})
    head_ids = [event_id_for(h.header) for h in heads]
    evidence = sorted({pr["ref"] for h in heads for pr in h.header["provenance"]} |
                      ({h.payload.get("source_event") for h in heads if h.payload.get("source_event")}))
    if len(values) == 1:
        return {"key": key, "status": "RESOLVED", "value": values[0], "heads": head_ids, "evidence": evidence}
    return {"key": key, "status": "CONFLICTED", "value": None, "heads": head_ids,
            "candidates": {event_id_for(h.header): value_of(h) for h in heads}, "evidence": evidence}


def current_heads(node, key: str) -> list:
    return resolve(node, key)["heads"]


def reconcile_all(node) -> dict:
    """Recompute every keyed state; persist newly detected conflicts (with a
    receipt) and mark conflicts whose key is now resolved. Deterministic."""
    view = {}
    for key, evs in sorted(assertions_by_key(node).items()):
        view[key] = resolve(node, key, evs)
    with node.tx() as conn:
        open_rows = {r[0]: r[1] for r in conn.execute(
            "SELECT conflict_id, key FROM conflicts WHERE kind='STATE' AND status='OPEN'")}
        new = []
        for key, r in view.items():
            if r["status"] == "CONFLICTED":
                cid = "cf_" + digest("conflict", ["STATE", key, r["heads"]])
                if conn.execute("SELECT 1 FROM conflicts WHERE conflict_id=?", (cid,)).fetchone() is None:
                    conn.execute("INSERT INTO conflicts VALUES(?,?,?,?,?)",
                                 (cid, "STATE", key, json.dumps({"candidates": r["candidates"]}, sort_keys=True),
                                  "OPEN"))
                    new.append(cid)
        resolved = []
        for cid, key in open_rows.items():
            if view.get(key, {}).get("status") == "RESOLVED":
                conn.execute("UPDATE conflicts SET status='RESOLVED' WHERE conflict_id=?", (cid,))
                resolved.append(cid)
        if new or resolved:
            s = node.state_digest()
            receipts.issue(node, conn, "CONFLICTS_RECONCILED", new + resolved, s, s,
                           {"detected": sorted(new), "resolved": sorted(resolved)})
    return view


def open_conflicts(node) -> list:
    return [{"conflict_id": r[0], "kind": r[1], "key": r[2], "detail": json.loads(r[3])}
            for r in node.conn.execute("SELECT conflict_id, kind, key, detail FROM conflicts "
                                       "WHERE status='OPEN' ORDER BY conflict_id")]


def resolve_conflict(node, key: str, value: str, *, actor: str, note: str = ""):
    """Human resolution: causally follows every current head of the key."""
    heads = current_heads(node, key)
    ev = node.append("CONFLICT_RESOLVED", {"key": key, "value": value, "resolved_heads": heads,
                                           "note": note or "operator resolution"},
                     actor=actor, parents=heads, privacy="PRIVATE")
    reconcile_all(node)
    return ev
