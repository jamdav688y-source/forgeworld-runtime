"""The physical-experiment runner (omega/experiment.py), exercised end to end
over LOOPBACK in one machine. This proves the procedure works; it is not the
physical result. The report refuses all_ok unless the phone record says
Android/Termux and the PC record says Windows."""
import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from omega import experiment as ex
from omega.identity import parse_offer, short_auth_string
from omega.store import Node

ROOT = Path(__file__).resolve().parent.parent.parent
PASS = "experiment test passphrase"


def ns(**kw):
    return argparse.Namespace(**kw)


def init(d, role, monkeypatch):
    monkeypatch.setattr(ex, "_passphrase", lambda prompt: PASS)
    assert ex.cmd_init(ns(dir=str(d), role=role, label=role, operator="owner"))


def test_full_experiment_over_loopback(tmp_path, monkeypatch):
    ph, pc = tmp_path / "phone", tmp_path / "pc"
    init(ph, "phone", monkeypatch)
    init(pc, "pc", monkeypatch)
    # pairing (normally the CLI `omega pair`, with the SAS compared by eye)
    a, b = Node.open(ex._home(ph)), Node.open(ex._home(pc))
    oa, ob = parse_offer(a.pairing_offer()), parse_offer(b.pairing_offer())
    sas = short_auth_string(oa, ob)
    a.add_peer(ob, oa, sas, actor="human:owner", operator=a.unlock_operator(PASS))
    b.add_peer(oa, ob, sas, actor="human:owner", operator=b.unlock_operator(PASS))
    a.close(); b.close()

    monkeypatch.setattr(ex, "_network_reachable", lambda: False)   # stands in for airplane mode
    assert ex.cmd_capture(ns(dir=str(ph), operator="owner"))
    # recall in a NEW process, like reopening Termux
    r = subprocess.run([sys.executable, "-m", "omega.experiment", "recall", "--dir", str(ph)], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads(ex._record_path(ph, "phone").read_text())["steps"][-1]
    assert rec["facts"]["new_process"] and rec["facts"]["continuity_gate_blocks"] == ["REPEATED_QUESTION"]

    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("ok", ex.cmd_serve(ns(dir=str(pc), host="127.0.0.1", port=port, timeout=30))))
    t.start()
    import time
    time.sleep(0.5)
    assert ex.cmd_sync(ns(dir=str(ph), host="127.0.0.1", port=port, timeout=30))
    t.join(40)
    assert out["ok"]
    sync_rec = json.loads(ex._record_path(ph, "phone").read_text())["steps"][-1]["facts"]
    assert sync_rec["first"]["sent"] > 0 and sync_rec["second"]["sent"] == 0 and sync_rec["second"]["imported"] == 0

    assert ex.cmd_verify(ns(dir=str(pc), phone_record=str(ex._record_path(ph, "phone"))))
    v = json.loads(ex._record_path(pc, "pc").read_text())["steps"][-1]["facts"]
    assert v["signed_by_phone"] and v["same_context_as_phone"] and v["recalled_budget"] == "$2,500"

    verdict = tmp_path / "verdict.json"
    ok = ex.cmd_report(ns(phone=str(ex._record_path(ph, "phone")), pc=str(ex._record_path(pc, "pc")), out=str(verdict)))
    doc = json.loads(verdict.read_text())
    assert all(c["ok"] for c in doc["checks"].values())          # every step passed...
    assert ok is False and doc["all_ok"] is False                 # ...but this is not Android + Windows
    from omega import proof
    assert proof.verify_file(verdict)["untampered"]


def test_capture_with_network_is_not_counted_as_offline(tmp_path, monkeypatch):
    d = tmp_path / "p"
    init(d, "phone", monkeypatch)
    monkeypatch.setattr(ex, "_network_reachable", lambda: True)
    assert ex.cmd_capture(ns(dir=str(d), operator="owner")) is False
