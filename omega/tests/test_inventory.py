"""The capability inventory may not claim more than the repository proves:
every VERIFIED component must name existing code and existing tests."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INV = ROOT / "docs" / "omega" / "capability_inventory.json"


def test_inventory_is_well_formed_and_honest():
    inv = json.loads(INV.read_text())
    ids = [c["id"] for c in inv["components"]]
    assert len(ids) == len(set(ids))
    for c in inv["components"]:
        assert c["status"] in inv["statuses"], c
        for p in c["paths"]:
            assert (ROOT / p).exists(), (c["id"], p)
        for e in c["evidence"]:
            assert (ROOT / e).exists(), (c["id"], e)
        if c["status"] == "VERIFIED":
            assert c["paths"] and c["evidence"], c["id"]
            assert any("test" in e for e in c["evidence"]), c["id"]
        if c["status"] in ("PARTIAL", "MISSING", "BLOCKED", "PRESENT_BUT_UNTESTED") and c["id"].startswith(("omega_", "android", "windows")):
            assert c.get("note") or c["status"] == "MISSING", c["id"]
