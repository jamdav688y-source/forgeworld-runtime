"""The proof harness: checks run for real, files are signed, tampering and
code drift are detected."""
import json

from omega import proof


def test_signed_proof_round_trip_and_tamper_detection(tmp_path):
    out = tmp_path / "p.json"
    doc = {"schema": "fw.omega.proof/1", "device": "test", "started_utc": "x", "platform": proof._platform(),
           "sources": proof._sources(), "checks": {"restart": proof.check_restart(), "ratio": {"ok": True, "v": 0.5}},
           "all_ok": True}
    proof._sign(doc, out)
    v = proof.verify_file(out)
    assert v["untampered"] and v["checks"]["restart"] and v["source_files_differing_from_this_checkout"] == []
    d = json.loads(out.read_text())
    assert d["checks"]["ratio"]["v"] == "0.500"            # floats encoded, never hashed as floats
    d["checks"]["restart"]["ok"] = False
    out.write_text(json.dumps(d))
    assert not proof.verify_file(out)["untampered"]


def test_source_drift_is_reported(tmp_path):
    out = tmp_path / "p.json"
    src = proof._sources()
    src["omega/store.py"] = "0" * 64
    proof._sign({"schema": "fw.omega.proof/1", "device": "t", "platform": {"platform": "x"}, "sources": src,
                 "checks": {}, "all_ok": True}, out)
    assert proof.verify_file(out)["source_files_differing_from_this_checkout"] == ["omega/store.py"]


def test_key_byte_check_runs():
    r = proof.check_key_bytes()
    assert r["ok"] and r["identities_created"] == 200
