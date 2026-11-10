"""The single operator entry point: verdict logic, skip classification, and
a BLOCKED run that still preserves its evidence."""
import json
import sys

import pytest

from omega import gate


def rep(checks=None, missing=None, kind="android"):
    return {"environment": {"kind": kind}, "missing": missing or [], "checks": checks or {}}


def test_verdicts():
    ok = {"ok": True}
    assert gate.verdict_for(rep({"test_suite": ok, "key_bytes": ok, "restart": ok, "e2e": ok}))[0] == "PASS"
    v, why = gate.verdict_for(rep({"test_suite": {"ok": False, "failures": ["omega/tests/x.py::t"]}, "e2e": ok}))
    assert v == "FAIL" and "omega/tests/x.py::t" in why
    v, why = gate.verdict_for(rep({"key_bytes": {"ok": False}}))
    assert v == "FAIL" and "do NOT pair" in why
    v, why = gate.verdict_for(rep(missing=["the 'cryptography' package"]))
    assert v == "BLOCKED" and "pkg install" in why


def test_optional_ollama_skip_does_not_block_but_other_skips_do(tmp_path, monkeypatch):
    class R:
        returncode = 0
        stderr = ""
        stdout = ("..s\nSKIPPED [1] omega/tests/test_bench.py:50: no local Ollama with the test model\n"
                  "3 passed, 1 skipped in 0.1s\n")
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: R())
    r = gate.run_tests(tmp_path / "log")
    assert r["ok"] and r["skips"][0]["release_relevant"] is False and r["counts"] == {"passed": 3, "skipped": 1}
    R.stdout = "s\nSKIPPED [1] omega/tests/test_sync.py:9: sqlite too old\n1 skipped in 0.1s\n"
    assert gate.run_tests(tmp_path / "log2")["ok"] is False


def test_blocked_run_preserves_evidence_and_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "prerequisites", lambda env: ["the 'cryptography' package"])
    with pytest.raises(SystemExit) as e:
        gate.main(["--evidence", str(tmp_path), "--device", "test"])
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert "VERDICT: BLOCKED" in out
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1 and (runs[0] / "verdict.txt").exists()
    assert json.loads((runs[0] / "report.json").read_text())["verdict"] == "BLOCKED"
