"""Forge substrate extensions for the Windows / PC node (Stage D).

    OllamaClient     local model access over Ollama's HTTP API. Loopback only
                     unless the operator passes allow_remote=True (rule 8: no
                     private record leaves the machine without authorization).
    hardware_profile what this machine has (CPU, RAM, OS) -> hardware_class
    run_benchmark    fixed, deterministic evaluation suite; every result is a
                     BENCHMARK_RESULT event (score per-mille, median latency)
    ModelRouter      picks a model per task class from RECORDED BENCHMARK
                     EVIDENCE on THIS hardware class (never by parameter
                     count or name); falls back to the deterministic,
                     model-free path when no model meets the bar
    analyze_repository  repository facts (files, tests, governance digest, HEAD)
    run_command      bounded subprocess runner used by tests / the promotion gate

All optional: with Ollama absent, everything degrades to the deterministic
template drafter and the router says so explicitly (selected = None).
"""
from __future__ import annotations

import ipaddress
import json
import os
import platform
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from omega.canonical import digest, sha256_hex
from omega.events import event_id_for
from omega.relationship import MONEY_RE, classify_question, money_value, questions_in

BENCH_ACTOR = "tool:omega-benchmark"


class ModelUnavailable(RuntimeError):
    pass


def _is_loopback(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 120, allow_remote: bool = False):
        if not _is_loopback(base_url) and not allow_remote:
            raise PermissionError("refusing a non-loopback model endpoint without explicit operator authorization")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _req(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ModelUnavailable(str(exc))

    def available(self) -> bool:
        try:
            self._req("/api/tags")
            return True
        except ModelUnavailable:
            return False

    def models(self) -> list:
        return sorted(m["name"] for m in self._req("/api/tags").get("models", []))

    def generate(self, model: str, prompt: str, system: str = "") -> str:
        body = {"model": model, "prompt": prompt, "system": system, "stream": False,
                "options": {"temperature": 0, "seed": 0}}
        return self._req("/api/generate", body).get("response", "").strip()

    def repeat_checker(self, model: str, contact: str = "the contact") -> Callable:
        """Advisory semantic repeat check for RelationshipMemory.check_draft."""
        from omega.bench.memory_bench import PROMPT

        def check(pairs: list, question: str) -> bool:
            qa = "\n".join(f'- Q: "{p["q"]}"  A: "{p["a"]}"' for p in pairs)
            ans = self.generate(model, PROMPT.format(contact=contact, qa=qa, q=question)).strip()
            return bool(ans) and ans.split()[0].strip(".,!").upper() == "YES"
        check.name = f"ollama:{model}"
        return check

    def drafter(self, model: str) -> Callable:
        """A generator for RelationshipMemory.compose(). It sees only the one
        contact's reconstructed context."""
        def gen(ctx: dict, intent: str) -> str:
            known = {a: f["value"] for a, f in ctx["facts"].items() if f["status"] == "RESOLVED"}
            last = ctx["timeline"][-3:]
            prompt = (f"Write a short, polite {intent} message to {ctx['contact']['display_name']}.\n"
                      f"Known facts (do NOT ask about these again): {json.dumps(known, sort_keys=True)}\n"
                      f"Open commitments we owe: {[c['text'] for c in ctx['commitments'] if c['owed_by'] == 'US' and c['status'] == 'OPEN']}\n"
                      f"Recent messages: {json.dumps([(m['direction'], m['text']) for m in last])}\n"
                      "Do not invent familiarity or facts. Output only the message.")
            return self.generate(model, prompt, system="You draft messages for a human to review. Never send.")
        gen.name = f"ollama:{model}"
        return gen


# ---------------------------------------------------------------- hardware
def _ram_bytes() -> Optional[int]:
    try:
        if os.path.exists("/proc/meminfo"):
            for line in open("/proc/meminfo"):
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        if platform.system() == "Windows":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys)
    except Exception:
        return None
    return None


def hardware_profile() -> dict:
    ram = _ram_bytes()
    cpus = os.cpu_count() or 1
    system = "android" if "ANDROID_ROOT" in os.environ else platform.system().lower()
    ram_gb = (ram // (1024 ** 3)) if ram else None
    bucket = "unknown" if ram_gb is None else ("<=4" if ram_gb <= 4 else "<=8" if ram_gb <= 8 else
                                                "<=16" if ram_gb <= 16 else "<=32" if ram_gb <= 32 else ">32")
    return {"system": system, "machine": platform.machine(), "cpus": cpus, "ram_bytes": ram,
            "hardware_class": f"{system}-{platform.machine()}-ram{bucket}gb-{cpus}c"}


# --------------------------------------------------------------- benchmark
def _check_budget(out: str) -> bool:
    m = MONEY_RE.search(out) or None
    return money_value(m.group(0) if m else out) == 5000


def _check_no_budget_q(out: str) -> bool:
    return bool(out.strip()) and not any(classify_question(q) == "budget" for q in questions_in(out))


SUITE = [
    {"id": "extract-budget-1", "task_class": "extraction",
     "prompt": "From this message, output only the budget amount: 'We can spend around $5,000 on phase one.'",
     "check": _check_budget},
    {"id": "extract-budget-2", "task_class": "extraction",
     "prompt": "Output only the budget figure in this text: 'Our ceiling is 5k USD, maybe less.'",
     "check": _check_budget},
    {"id": "no-repeat-1", "task_class": "drafting",
     "prompt": ("The customer already told us their budget is $5,000. Write a two-sentence follow-up "
                "asking about their timeline. Do not ask about budget."),
     "check": _check_no_budget_q},
]
SUITE_DIGEST = "bs_" + digest("bench-suite", [[c["id"], c["task_class"], c["prompt"]] for c in SUITE])


def run_benchmark(node, client, models: list, hw: Optional[dict] = None, clock=time.perf_counter) -> list:
    hw = hw or hardware_profile()
    written = []
    for model in models:
        by_class = {}
        for case in SUITE:
            t0 = clock()
            try:
                out = client.generate(model, case["prompt"])
                ok = bool(case["check"](out))
            except ModelUnavailable:
                out, ok = "", False
            ms = int((clock() - t0) * 1000)
            by_class.setdefault(case["task_class"], []).append((ok, ms))
        for tc, rs in sorted(by_class.items()):
            score = int(1000 * sum(ok for ok, _ in rs) / len(rs))
            ev = node.append("BENCHMARK_RESULT",
                             {"model": model, "task_class": tc, "suite_digest": SUITE_DIGEST, "score_permille": score,
                              "latency_ms": int(statistics.median(ms for _, ms in rs)), "cases": len(rs),
                              "hardware_class": hw["hardware_class"]},
                             actor=BENCH_ACTOR, privacy="INTERNAL",
                             provenance=[{"kind": "tool", "ref": f"ollama:{model}"}])
            written.append(ev)
    return written


class ModelRouter:
    MIN_SCORE = 600

    def __init__(self, node):
        self.node = node

    @staticmethod
    def suites() -> set:
        """Benchmark suites whose results the router accepts: the built-in
        routing suite and the frozen memory benchmark case file."""
        from omega.bench.memory_bench import load
        return {SUITE_DIGEST, "mb_" + load()[1][:32]}

    def select(self, task_class: str, hardware_class: Optional[str] = None, max_latency_ms: int = 30000,
               available: Optional[list] = None) -> dict:
        hw = hardware_class or hardware_profile()["hardware_class"]
        latest = {}
        for e in self.node.events("BENCHMARK_RESULT"):
            p = e.payload
            if (p and p["task_class"] == task_class and p["hardware_class"] == hw
                    and p["suite_digest"] in self.suites()):
                latest[p["model"]] = (p, event_id_for(e.header))   # later evidence replaces earlier
        cands = []
        for model, (p, eid) in sorted(latest.items()):
            reason = None
            if available is not None and model not in available:
                reason = "NOT_INSTALLED"
            elif p["latency_ms"] > max_latency_ms:
                reason = "TOO_SLOW_ON_THIS_HARDWARE"
            elif p["score_permille"] < self.MIN_SCORE:
                reason = "BELOW_QUALITY_BAR"
            cands.append({"model": model, "score_permille": p["score_permille"], "latency_ms": p["latency_ms"],
                          "evidence": eid, "excluded": reason})
        ok = sorted((c for c in cands if c["excluded"] is None),
                    key=lambda c: (-c["score_permille"], c["latency_ms"], c["model"]))
        if not ok:
            return {"task_class": task_class, "hardware_class": hw, "selected": None,
                    "fallback": "deterministic", "reason": "no benchmarked model meets the bar on this hardware",
                    "candidates": cands}
        return {"task_class": task_class, "hardware_class": hw, "selected": ok[0]["model"], "fallback": None,
                "reason": "highest recorded benchmark score, then lowest latency", "evidence": ok[0]["evidence"],
                "candidates": cands}


# ------------------------------------------------------------ repository
def run_command(cmd: list, cwd, timeout: int = 1800) -> dict:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "exit_code": r.returncode, "stdout_tail": r.stdout[-4000:], "stderr_tail": r.stderr[-2000:],
                "stdout_sha256": sha256_hex(r.stdout.encode())}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"cmd": cmd, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}


def governance_digest(root) -> str:
    from omega.evolution import GOVERNANCE_PATHS
    root = Path(root)
    files = []
    for rel in GOVERNANCE_PATHS:
        p = root / rel
        if p.is_dir():
            files += sorted(x for x in p.rglob("*") if x.is_file())
        elif p.is_file():
            files.append(p)
    return "gv_" + digest("governance", [[str(f.relative_to(root)).replace(os.sep, "/"),
                                          sha256_hex(f.read_bytes())] for f in files])


def analyze_repository(root) -> dict:
    root = Path(root)
    exts, tests, py = {}, [], []
    for p in root.rglob("*"):
        if ".git" in p.parts or "__pycache__" in p.parts or not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace(os.sep, "/")
        exts[p.suffix or "(none)"] = exts.get(p.suffix or "(none)", 0) + 1
        if p.suffix == ".py":
            py.append(rel)
            if p.name.startswith("test_"):
                tests.append(rel)
    head = run_command(["git", "rev-parse", "HEAD"], root, timeout=20)
    return {"root": root.name, "files_by_extension": dict(sorted(exts.items())), "python_modules": len(py),
            "test_files": sorted(tests), "git_head": (head.get("stdout_tail") or "").strip() or None,
            "governance_digest": governance_digest(root)}
