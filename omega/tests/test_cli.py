"""The operator CLI, driven exactly as on the phone / PC (separate processes)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


PASS = "phone and pc test passphrase\n"


def omega(home, *args, check=True, passphrase=None):
    pre = ["--passphrase-stdin"] if passphrase is not None else []
    r = subprocess.run([sys.executable, "-m", "omega", "--home", str(home), *pre, *args], cwd=ROOT,
                       capture_output=True, text=True, input=passphrase)
    if check and r.returncode != 0:
        raise AssertionError(f"{args}: rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def j(r):
    return json.loads(r.stdout)


def test_cli_pairing_capture_draft_and_bundle_handoff(tmp_path):
    ph, pc = tmp_path / "phone", tmp_path / "pc"
    omega(ph, "init", "--label", "phone", "--profile", "pocket")
    omega(pc, "init", "--label", "pc", "--profile", "forge")
    for h in (ph, pc):
        assert j(omega(h, "operator-init", "--name", "op", passphrase=PASS))["actor"] == "human:op"
    o_ph, o_pc = omega(ph, "offer").stdout.strip(), omega(pc, "offer").stdout.strip()
    shown = omega(ph, "pair", "--offer", o_pc, "--my-offer", o_ph, "--actor", "human:op", check=False)
    assert shown.returncode == 3
    sas = shown.stdout.split("SAS: ")[1][:6]
    shown_pc = omega(pc, "pair", "--offer", o_ph, "--my-offer", o_pc, "--actor", "human:op", check=False)
    assert shown_pc.stdout.split("SAS: ")[1][:6] == sas          # both screens agree
    bad = omega(ph, "pair", "--offer", o_pc, "--my-offer", o_ph, "--sas", "000000" if sas != "000000" else "111111",
                "--actor", "human:op", check=False, passphrase=PASS)
    assert bad.returncode != 0 and "mismatch" in bad.stderr
    omega(ph, "pair", "--offer", o_pc, "--my-offer", o_ph, "--sas", sas, passphrase=PASS)
    omega(pc, "pair", "--offer", o_ph, "--my-offer", o_pc, "--sas", sas, passphrase=PASS)

    cid = j(omega(ph, "contact-add", "--name", "Dana Reyes", "--primary", "sms:+15550100", "--actor", "human:op"))["contact_id"]
    omega(ph, "message", "--contact", cid, "--direction", "OUT", "--text", "Hi Dana, what budget do you have in mind?",
          "--at", "2026-11-01T10:00:00Z", "--source", "sms:t#1", "--actor", "human:op")
    m = j(omega(ph, "message", "--contact", cid, "--direction", "IN", "--text", "About $5,000.",
                "--at", "2026-11-01T10:05:00Z", "--source", "sms:t#2", "--actor", "tool:sms-import"))
    assert m["facts"][0]["attribute"] == "budget"
    chk = j(omega(ph, "check-draft", "--contact", cid, "--text", "Hi Dana, what's your budget?"))
    assert chk[0]["code"] == "REPEATED_QUESTION"
    d = j(omega(ph, "draft", "--contact", cid, "--intent", "discovery"))
    assert "budget range" not in d["text"]

    pc_id = j(omega(pc, "diag"))["node"]["device_id"]
    bundle = tmp_path / "to-pc.fwbundle"
    omega(ph, "bundle-export", "--peer", pc_id, "--out", str(bundle))
    rep = j(omega(pc, "bundle-import", str(bundle)))
    assert rep["complete"] and len(rep["imported"]) >= 6
    replay = omega(pc, "bundle-import", str(bundle), check=False)
    assert replay.returncode != 0 and "REPLAY_DETECTED" in replay.stderr
    ctx = j(omega(pc, "context", "--contact", cid))
    assert ctx["facts"]["budget"]["value"] == "$5,000"
    assert omega(pc, "verify").returncode == 0
    t = j(omega(pc, "task-queue", "--action", "noop", "--actor", "human:op", "--external"))["task_id"]
    assert j(omega(pc, "task-run")) == [[t, "AWAITING_AUTHORIZATION"]]
    wrong = omega(pc, "task-authorize", "--task", t, check=False, passphrase="guess\n")
    assert wrong.returncode != 0 and "PASSPHRASE_WRONG" in wrong.stderr
    imposter = omega(pc, "task-authorize", "--task", t, "--actor", "human:someone-else", check=False, passphrase=PASS)
    assert imposter.returncode != 0
    assert j(omega(pc, "task-run")) == [[t, "AWAITING_AUTHORIZATION"]]
    omega(pc, "task-authorize", "--task", t, passphrase=PASS)
    assert j(omega(pc, "task-run")) == [[t, "SUCCEEDED"]]
    omega(pc, "backup", "--out", str(tmp_path / "pc-backup.db"))
    assert (tmp_path / "pc-backup.db").stat().st_size > 0
