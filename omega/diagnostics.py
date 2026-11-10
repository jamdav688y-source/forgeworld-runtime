"""Exportable diagnostic report / mission-control projection.

Read-only (it never writes an event). Follows the rules of
docs/architecture/MISSION_CONTROL_DATA_CONTRACT.md: derived on read, absence
shown as absence, no actions. It carries NO payload text, so it is safe to
export from the phone for troubleshooting: counts, ids, digests, states.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from omega import PACKAGE_VERSION, receipts, reconcile
from omega.identity import HAVE_CRYPTO


def report(node, probe_ollama: bool = False) -> dict:
    c = node.conn
    types = Counter(r[0] for r in c.execute("SELECT event_type FROM events"))
    states = Counter(r[0] for r in c.execute("SELECT payload_state FROM events"))
    integrity = node.verify_integrity()
    rc = receipts.all_receipts(node)
    caps = {"cryptography": HAVE_CRYPTO, "fts5": node.fts5, "ollama": "NOT_PROBED"}
    if probe_ollama:
        from omega.forge import OllamaClient
        caps["ollama"] = "AVAILABLE" if OllamaClient(timeout=2).available() else "UNAVAILABLE"
    return {
        "schema": "fw.omega.diagnostics/1",
        "package_version": PACKAGE_VERSION,
        "node": {"device_id": node.device_id, "label": node.info.get("label"), "profile": node.info.get("profile")},
        "vector": node.vector(),
        "state_digest": node.state_digest(),
        "events_by_type": dict(sorted(types.items())),
        "payload_states": dict(sorted(states.items())),
        "peers": [{"device_id": p["device_id"], "label": p["label"], "max_privacy": p["max_privacy"],
                   "revoked": p["revoked"], "last_known_vector": p["last_vector"]} for p in node.peers()],
        "open_conflicts": [{"conflict_id": x["conflict_id"], "kind": x["kind"], "key": x["key"]}
                           for x in reconcile.open_conflicts(node)],
        "quarantine": dict(Counter(r[0] for r in c.execute("SELECT reason FROM quarantine"))),
        "local_tasks": dict(Counter(r[0] for r in c.execute("SELECT state FROM local_exec"))),
        "receipts": {"count": len(rc), "head": rc[-1]["receipt_id"] if rc else None},
        "integrity": {"ok": integrity["ok"], "problems": [list(map(str, p)) for p in integrity["problems"]]},
        "capabilities": caps,
    }


def export(node, path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report(node), indent=2, sort_keys=True))
    return path
