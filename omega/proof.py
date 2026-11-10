"""Platform proof harness: produce a signed, independently checkable evidence
file on the machine where it runs.

    python -m omega.proof run --device "<what this machine is>" --out proof.json [--ollama-model M ...]
    python -m omega.proof lan-serve --home <node> --host <LAN IP>     # on the PC
    python -m omega.proof lan-sync  --home <node> --host <PC LAN IP>  # on the phone
    python -m omega.proof verify proof.json                           # anyone, anywhere

Checks (each records what was run and what happened; nothing is assumed):
    platform      OS, machine, Python, SQLite (+FTS5), cryptography, Termux/Windows detection
    key_bytes     the Windows line-ending defect: 0..255 bytes and 200 real
                  key generations written and re-read byte-exactly
    test_suite    `pytest omega/tests` in a subprocess (pass/fail counts)
    e2e           the acceptance scenario (omega.demo_e2e)
    restart       process A writes and exits; process B reopens and verifies;
                  process C is killed (os._exit) inside a transaction; D verifies
    ollama        optional: real model benchmark + evidence-based routing +
                  the memory benchmark against the deterministic baseline

The proof file is signed by a proof identity created for the run, and it
lists the sha256 of every omega source file, so a reader can tie the result
to an exact code version. The signature shows the file was not edited after
the run. It does NOT prove which hardware ran it: the `device` field is the
operator's statement, backed by the platform fingerprint.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omega.canonical import canonical, digest, sha256_hex  # noqa: E402


def _platform() -> dict:
    fts5 = True
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError:
        fts5 = False
    try:
        import cryptography
        cver = cryptography.__version__
    except ImportError:
        cver = None
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "omega"], cwd=ROOT, capture_output=True, text=True)
    return {"system": platform.system(), "release": platform.release(), "platform": platform.platform(),
            "machine": platform.machine(), "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "fts5": fts5, "cryptography": cver, "termux": "com.termux" in os.environ.get("PREFIX", ""),
            "android": "ANDROID_ROOT" in os.environ, "windows": os.name == "nt", "cpus": os.cpu_count(),
            "git_commit": git.stdout.strip() or None, "omega_dirty": bool(dirty.stdout.strip())}


def _sources() -> dict:
    return {str(p.relative_to(ROOT)).replace(os.sep, "/"): sha256_hex(p.read_bytes())
            for p in sorted((ROOT / "omega").rglob("*.py")) if "__pycache__" not in p.parts}


def check_key_bytes() -> dict:
    from omega.identity import DeviceIdentity, _write_secret
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "k"
        data = bytes(range(256))
        _write_secret(p, data)
        raw_ok = p.read_bytes() == data
        with_newline, failures = 0, []
        for i in range(200):
            sub = Path(d) / f"id{i}"
            ident = DeviceIdentity.create(sub)
            raw = (sub / "sign.key").read_bytes() + (sub / "kx.key").read_bytes()
            with_newline += (b"\n" in raw)
            try:
                if DeviceIdentity.load(sub).device_id != ident.device_id:
                    failures.append(i)
            except Exception as exc:
                failures.append(f"{i}:{type(exc).__name__}")
    return {"ok": raw_ok and not failures, "all_256_byte_values_round_trip": raw_ok, "identities_created": 200,
            "identities_whose_key_bytes_contain_0x0A": with_newline, "reload_failures": failures}


def check_tests(timeout=1800) -> dict:
    t = time.time()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "omega/tests"], cwd=ROOT,
                       capture_output=True, text=True, timeout=timeout)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error|errors)", tail[0])}
    return {"ok": r.returncode == 0, "exit_code": r.returncode, "summary": tail[0], "counts": counts,
            "seconds": int(time.time() - t), "failures": re.findall(r"^FAILED (\S+)", r.stdout, re.M)[:50]}


def check_e2e() -> dict:
    from omega import demo_e2e
    with tempfile.TemporaryDirectory() as d:
        r = demo_e2e.run(d)
        for n in r.pop("_nodes"):
            n.close()
    keys = ("sync_complete", "pc_integrity", "same_context", "sync_back_complete", "vectors_equal",
            "state_digests_equal", "final_integrity")
    ok = all(r[k] for k in keys) and r["after_authorization"] == "SUCCEEDED" \
        and r["before_authorization"] == "AWAITING_AUTHORIZATION" \
        and r["forged_authorization"] == "OPERATOR_ATTESTATION_REQUIRED"
    return {"ok": ok, **{k: r[k] for k in keys}, "naive_draft_blocked": r["naive_draft_blocked"],
            "forged_authorization": r["forged_authorization"], "before_authorization": r["before_authorization"],
            "after_authorization": r["after_authorization"], "sent_reply": r["sent_reply"]}


_CHILD = """
import sys, json
sys.path.insert(0, {root!r})
from omega.store import Node
n = Node.open({home!r})
for i in range({k}):
    n.append("NOTE_RECORDED", {{"text": "restart proof " + str(i)}}, actor="human:proof")
print(json.dumps(n.vector()))
"""


def check_restart() -> dict:
    from omega.store import Node
    with tempfile.TemporaryDirectory() as d:
        home = str(Path(d) / "node")
        Node.init(home, "restart-proof").close()
        env = dict(os.environ)
        env.pop("OMEGA_FAULT", None)
        a = subprocess.run([sys.executable, "-c", _CHILD.format(root=str(ROOT), home=home, k=5)], env=env,
                           capture_output=True, text=True)
        n = Node.open(home)
        after_a = n.vector().get(n.device_id, 0)
        integ_a = n.verify_integrity()["ok"]
        n.close()
        env["OMEGA_FAULT"] = "append:after_insert"
        c = subprocess.run([sys.executable, "-c", _CHILD.format(root=str(ROOT), home=home, k=1)], env=env,
                           capture_output=True, text=True)
        n = Node.open(home)
        after_c = n.vector().get(n.device_id, 0)
        integ_c = n.verify_integrity()
        n.close()
    ok = a.returncode == 0 and after_a == 5 and integ_a and c.returncode == 91 and after_c == 5 and integ_c["ok"]
    return {"ok": ok, "writer_exit": a.returncode, "events_after_clean_restart": after_a,
            "integrity_after_clean_restart": integ_a, "killed_writer_exit": c.returncode,
            "events_after_kill": after_c, "integrity_after_kill": integ_c["ok"],
            "note": "the killed process died inside its transaction; nothing partial may remain"}


def check_ollama(models: list, url: str) -> dict:
    from omega import forge
    from omega.bench import memory_bench
    from omega.store import Node
    client = forge.OllamaClient(url, timeout=600)
    if not client.available():
        return {"ok": False, "status": "UNAVAILABLE", "url": url}
    hw = forge.hardware_profile()
    with tempfile.TemporaryDirectory() as d:
        n = Node.init(Path(d) / "n", "ollama-proof", "forge")
        for m in models:
            client.generate(m, "Reply OK.")
        evs = forge.run_benchmark(n, client, models, hw=hw)
        with tempfile.TemporaryDirectory() as d2:
            out = Path(d2) / "mb.json"
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):   # keep operator output readable
                memory_bench.main(["--out", str(out), "--ollama", url] + sum((["--model", m] for m in models), []))
            mb = json.loads(out.read_text())
        evs += memory_bench.record_as_benchmark(n, mb, hw)
        bench = [{k: e.payload[k] for k in ("model", "task_class", "score_permille", "latency_ms", "cases")} for e in evs]
        routes = {tc: forge.ModelRouter(n).select(tc, hardware_class=hw["hardware_class"], available=client.models())
                  for tc in ("extraction", "drafting", "repeat_detection")}
        n.close()
    return {"ok": True, "status": "AVAILABLE", "version": client._req("/api/version").get("version"),
            "hardware": hw, "routing_benchmark": bench,
            "routing": {tc: {"selected": r["selected"], "fallback": r["fallback"], "reason": r["reason"]}
                        for tc, r in routes.items()},
            "memory_benchmark": {"cases_sha256": mb["cases_sha256"],
                                 "systems": {k: {"overall": v["overall"],
                                                 "paraphrase_recall": v["by_kind"]["paraphrase"]["recall"],
                                                 "near_miss_fp": v["by_kind"]["near_miss"]["fp"],
                                                 "new_fp": v["by_kind"]["new"]["fp"],
                                                 "median_ms": v["latency_ms"]["median"]}
                                             for k, v in mb["systems"].items()}}}


def _no_floats(x):
    """Canonical JSON forbids floats: ratios are recorded as fixed 3-decimal strings."""
    if isinstance(x, float):
        return f"{x:.3f}"
    if isinstance(x, dict):
        return {k: _no_floats(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_no_floats(v) for v in x]
    return x


def _sign(doc: dict, out: Path) -> dict:
    from omega.identity import DeviceIdentity, b64e
    with tempfile.TemporaryDirectory() as d:
        ident = DeviceIdentity.create(Path(d) / "proof-id")
        body = _no_floats(dict(doc))
        body["signer"] = {"device_id": ident.device_id, "sign_pub": b64e(ident.sign_pub)}
        body["proof_id"] = "pf_" + digest("proof", body)
        body["signature"] = ident.sign(body["proof_id"].encode())
    out.write_text(json.dumps(body, indent=2, sort_keys=True))
    return body


def verify_file(path) -> dict:
    from omega.identity import b64d, device_id_for, verify
    doc = json.loads(Path(path).read_text())
    sig, pid = doc.pop("signature"), doc.pop("proof_id")
    ok_id = "pf_" + digest("proof", doc) == pid
    pub = b64d(doc["signer"]["sign_pub"])
    ok_sig = verify(pub, sig, pid.encode()) and device_id_for(pub) == doc["signer"]["device_id"]
    cur = _sources()
    changed = sorted(k for k in set(cur) | set(doc["sources"]) if cur.get(k) != doc["sources"].get(k))
    return {"untampered": ok_id and ok_sig, "proof_id": pid, "device": doc["device"],
            "platform": doc["platform"]["platform"], "checks": {k: v.get("ok") for k, v in doc["checks"].items()},
            "source_files_differing_from_this_checkout": changed}


def run(device: str, out: Path, models: list, url: str, skip_tests: bool = False) -> dict:
    checks = {"key_bytes": check_key_bytes(), "restart": check_restart(), "e2e": check_e2e()}
    if not skip_tests:
        checks["test_suite"] = check_tests()
    if models:
        checks["ollama"] = check_ollama(models, url)
    doc = {"schema": "fw.omega.proof/1", "device": device, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "platform": _platform(), "sources": _sources(), "checks": checks,
           "all_ok": all(c.get("ok") for c in checks.values())}
    return _sign(doc, out)


# ------------------------------------------------------------------ LAN proof
def lan(role: str, home: str, host: str, port: int, peer: str, out: Path) -> dict:
    from omega import sync
    from omega.store import Node
    n = Node.open(home)
    before = n.vector()
    t = time.time()
    if role == "serve":
        reps = sync.serve(n, host, port, 1, timeout=600)
        rep = reps[0]
    else:
        rep = sync.sync_tcp(n, host, port, expect=peer)
    res = {"role": role, "host": host, "port": port, "seconds": round(time.time() - t, 3)}
    if isinstance(rep, Exception):
        res.update(ok=False, error=f"{type(rep).__name__}: {rep}")
    else:
        res.update(ok=rep.complete and not rep.problems, peer=rep.peer, sent=rep.sent, imported=len(rep.imported),
                   duplicates=rep.duplicates, problems=[list(map(str, p)) for p in rep.problems])
    res.update(vector_before=before, vector_after=n.vector(), integrity=n.verify_integrity()["ok"],
               state_digest=n.state_digest(), device_id=n.device_id)
    n.close()
    doc = {"schema": "fw.omega.lan-proof/1", "device": f"node {res['device_id']}", "platform": _platform(),
           "sources": _sources(), "checks": {"lan_sync": res}, "all_ok": res["ok"] and res["integrity"],
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return _sign(doc, out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="omega.proof")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("run")
    p.add_argument("--device", required=True, help='e.g. "Windows 11 desktop (owner\'s PC)" -- your statement')
    p.add_argument("--out", required=True)
    p.add_argument("--ollama-model", action="append", default=[])
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--skip-tests", action="store_true")
    for name in ("lan-serve", "lan-sync"):
        p = sp.add_parser(name)
        p.add_argument("--home", required=True)
        p.add_argument("--host", required=True)
        p.add_argument("--port", type=int, default=47470)
        p.add_argument("--peer")
        p.add_argument("--out", required=True)
    p = sp.add_parser("verify")
    p.add_argument("path")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        doc = run(a.device, Path(a.out), a.ollama_model, a.ollama, a.skip_tests)
        print(json.dumps({"proof_id": doc["proof_id"], "all_ok": doc["all_ok"],
                          "checks": {k: v.get("ok") for k, v in doc["checks"].items()}, "out": a.out}, indent=2))
        raise SystemExit(0 if doc["all_ok"] else 1)
    if a.cmd in ("lan-serve", "lan-sync"):
        doc = lan("serve" if a.cmd == "lan-serve" else "sync", a.home, a.host, a.port, a.peer, Path(a.out))
        print(json.dumps(doc["checks"]["lan_sync"], indent=2))
        raise SystemExit(0 if doc["all_ok"] else 1)
    print(json.dumps(verify_file(a.path), indent=2))


if __name__ == "__main__":
    main()
