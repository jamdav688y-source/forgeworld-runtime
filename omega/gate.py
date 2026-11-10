"""Single operator verification entry point: one command, one verdict.

    python -m omega.gate [--device "<what this machine is>"] [--ollama-model M] [--evidence DIR]

Prints exactly one of
    PASS     every required check passed on this machine
    FAIL     something ran and failed: a real finding (evidence preserved)
    BLOCKED  a prerequisite is missing: nothing was judged
followed by one plain-language next action. Exit codes: PASS 0, FAIL 1, BLOCKED 2.

Safe and idempotent: it never edits the repository or system Python and never
touches network services. Each run writes to a NEW timestamped folder
(default ./omega-evidence/<stamp>/): report.json (signed, verify with
`python -m omega.proof verify`), pytest.log (full output), verdict.txt.
Earlier runs are never overwritten, so failure evidence is preserved.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Skips that do not block a release of the node where they occur: the
# real-model test needs a local Ollama server, which is optional by design.
RELEASE_IRRELEVANT_SKIPS = ("no local Ollama with the test model",)

INSTALL_HINT = {
    "android": "pkg install -y python python-cryptography git",
    "windows": "py -m pip install cryptography pytest   (inside the venv created by windows-verify.ps1)",
    "other": "python -m pip install cryptography pytest   (inside a virtual environment)",
}


def environment() -> dict:
    from omega import proof
    p = proof._platform()
    kind = "android" if (p["termux"] or p["android"]) else "windows" if p["windows"] else "other"
    return {**p, "kind": kind}


def prerequisites(env: dict) -> list:
    missing = []
    if sys.version_info < (3, 9):
        missing.append(f"Python >= 3.9 (found {sys.version.split()[0]})")
    if env.get("cryptography") is None:
        missing.append("the 'cryptography' package")
    try:
        import pytest  # noqa: F401
    except ImportError:
        missing.append("pytest")
    if env.get("git_commit") is None:
        missing.append("a git checkout of forgeworld-runtime (run this inside the cloned repository)")
    return missing


def run_tests(log: Path, timeout: int = 1800) -> dict:
    t = time.time()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "omega/tests"],
                       cwd=_ROOT, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    log.write_text(out)
    summary = next((ln for ln in reversed(out.strip().splitlines()) if re.search(r"\d+ (passed|failed|error)", ln)), "")
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)", summary)}
    failures = re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M)
    skips = re.findall(r"^SKIPPED \[\d+\] (\S+): (.+)$", out, re.M)
    skip_items = [{"where": w, "reason": why.strip(),
                   "release_relevant": not any(k in why for k in RELEASE_IRRELEVANT_SKIPS)} for w, why in skips]
    ok = r.returncode == 0 and not failures and not any(s["release_relevant"] for s in skip_items)
    return {"ok": ok, "exit_code": r.returncode, "summary": summary, "counts": counts, "failures": failures,
            "skips": skip_items, "seconds": int(time.time() - t)}


def verdict_for(report: dict) -> tuple:
    """(VERDICT, next action) from a report dict. Pure, unit-tested."""
    if report.get("missing"):
        return "BLOCKED", ("Install the missing prerequisite(s): " + "; ".join(report["missing"]) +
                           f". Command: {INSTALL_HINT[report['environment']['kind']]}. Then run this again.")
    bad = [k for k, v in report["checks"].items() if not v.get("ok")]
    if not bad:
        return "PASS", ("This machine passed every required check. Next: run the phone<->PC experiment "
                        "(docs/omega/DEPLOYMENT_AND_EXPERIMENT.md section C).")
    first = bad[0]
    detail = {
        "test_suite": "failing tests: " + ", ".join(report["checks"].get("test_suite", {}).get("failures", [])[:5]
                                                    or ["see pytest.log"]),
        "key_bytes": "key files did not round-trip byte-exactly: do NOT pair this device yet",
        "restart": "data did not survive a process restart",
        "e2e": "the end-to-end scenario failed",
        "ollama": "the local model checks failed (is `ollama serve` running and the model pulled?)",
    }.get(first, first)
    return "FAIL", (f"{len(bad)} check(s) failed ({', '.join(bad)}); first: {detail}. "
                    "Send the evidence folder printed below; do not edit it.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="omega.gate")
    ap.add_argument("--device", default="", help="your description of this machine (recorded as your statement)")
    ap.add_argument("--ollama-model", action="append", default=[])
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--evidence", default="omega-evidence")
    a = ap.parse_args(argv)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ev = Path(a.evidence) / stamp
    ev.mkdir(parents=True, exist_ok=False)
    env = environment()
    report = {"schema": "fw.omega.gate/1", "device": a.device or f"unspecified {env['kind']} machine",
              "environment": env, "platform": env, "missing": prerequisites(env), "checks": {}}
    if not report["missing"]:
        from omega import proof
        print("running: test suite ...", flush=True)
        report["checks"]["test_suite"] = run_tests(ev / "pytest.log")
        for name, fn in (("key_bytes", proof.check_key_bytes), ("restart", proof.check_restart), ("e2e", proof.check_e2e)):
            print(f"running: {name} ...", flush=True)
            try:
                report["checks"][name] = fn()
            except Exception as exc:   # a crash is a finding, never hidden
                report["checks"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if a.ollama_model:
            print("running: ollama ...", flush=True)
            try:
                report["checks"]["ollama"] = proof.check_ollama(a.ollama_model, a.ollama)
            except Exception as exc:
                report["checks"]["ollama"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    verdict, action = verdict_for(report)
    report.update(verdict=verdict, next_action=action, all_ok=verdict == "PASS", sources=_sources_or_empty())
    from omega import proof
    try:
        signed = proof._sign(report, ev / "report.json")
        sig_note = f"report.json signed, proof_id {signed['proof_id'][:16]}..."
    except Exception as exc:   # e.g. BLOCKED because 'cryptography' is missing: still record, unsigned
        (ev / "report.json").write_text(json.dumps(proof._no_floats(report), indent=2, sort_keys=True, default=str))
        sig_note = f"report.json UNSIGNED ({type(exc).__name__}); signing needs the prerequisites above"
    text = (f"\nVERDICT: {verdict}\nNEXT:    {action}\nCOMMIT:  {env.get('git_commit')}  (local edits: {env.get('omega_dirty')})\n"
            f"EVIDENCE: {ev.resolve()}  ({sig_note})\n")
    tc = report["checks"].get("test_suite")
    if tc:
        text += f"TESTS:   {tc['summary']}\n"
        for s in tc["skips"]:
            text += f"SKIPPED: {s['where']} -- {s['reason']} ({'BLOCKS release' if s['release_relevant'] else 'optional component, does not block'})\n"
    (ev / "verdict.txt").write_text(text)
    print(text)
    raise SystemExit({"PASS": 0, "FAIL": 1, "BLOCKED": 2}[verdict])


def _sources_or_empty():
    try:
        from omega import proof
        return proof._sources()
    except Exception:
        return {}


if __name__ == "__main__":
    main()
