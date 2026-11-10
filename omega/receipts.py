"""Deterministic, hash-chained, signed evidence receipts.

A receipt records one MATERIAL TRANSITION of a node: an event appended, an
import batch, a sync session, a purge, a refused or executed task, a conflict
detected, a promotion decision.

    body = {
      "schema":       "fw.omega.receipt/1",
      "type":         transition type,
      "device_id":    the node that issued it,
      "index":        position in this node's receipt chain (0-based),
      "prev":         previous receipt_id or null,
      "subjects":     sorted ids the transition concerns,
      "state_before": state digest before (vector + purged set),
      "state_after":  state digest after,
      "detail":       canonical JSON detail (no floats, no wall-clock time)
    }
    receipt_id = "rc_" + sha256(domain "receipt", body)
    signature  = Ed25519(device key, receipt_id)

DETERMINISTIC: the body contains no wall-clock time and no randomness, so
the same transitions applied to the same state by the same device always
yield the same receipt ids (test_receipts proves it by replaying a run with a
cloned identity and a fixed clock and comparing the chains byte for byte).
"""
from __future__ import annotations

import json

from omega.canonical import canonical, digest
from omega.identity import verify

SCHEMA = "fw.omega.receipt/1"


def build(device_id, index, prev, rtype, subjects, before, after, detail) -> dict:
    return {"schema": SCHEMA, "type": rtype, "device_id": device_id, "index": index, "prev": prev,
            "subjects": sorted(set(subjects)), "state_before": before, "state_after": after,
            "detail": detail}


def receipt_id(body: dict) -> str:
    return "rc_" + digest("receipt", body)


def issue(node, conn, rtype, subjects, before, after, detail) -> dict:
    """Append a receipt inside the caller's open transaction."""
    row = conn.execute("SELECT idx, receipt_id FROM receipts ORDER BY idx DESC LIMIT 1").fetchone()
    index, prev = (row[0] + 1, row[1]) if row else (0, None)
    body = build(node.device_id, index, prev, rtype, subjects, before, after, detail)
    rid = receipt_id(body)
    conn.execute("INSERT INTO receipts(idx, receipt_id, body, signature) VALUES(?,?,?,?)",
                 (index, rid, canonical(body).decode("utf-8"), node.identity.sign(rid.encode("ascii"))))
    return {"receipt_id": rid, **body}


def issue_standalone(node, rtype, subjects, detail) -> dict:
    with node.tx() as conn:
        s = node.state_digest()
        return issue(node, conn, rtype, subjects, s, s, detail)


def all_receipts(node) -> list:
    return [{"receipt_id": r[0], "signature": r[2], **json.loads(r[1])}
            for r in node.conn.execute("SELECT receipt_id, body, signature FROM receipts ORDER BY idx")]


def verify_chain(node) -> list:
    problems, prev = [], None
    for i, (idx, rid, body, sig) in enumerate(node.conn.execute(
            "SELECT idx, receipt_id, body, signature FROM receipts ORDER BY idx")):
        b = json.loads(body)
        if idx != i or b.get("index") != i or b.get("prev") != prev:
            problems.append(("RECEIPT_CHAIN_BROKEN", rid))
        if receipt_id(b) != rid:
            problems.append(("RECEIPT_ID_MISMATCH", rid))
        if not verify(node.identity.sign_pub, sig, rid.encode("ascii")):
            problems.append(("RECEIPT_SIGNATURE_INVALID", rid))
        prev = rid
    return problems
