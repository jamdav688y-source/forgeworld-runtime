"""Conversation-memory benchmark: does a system recognise a question the
contact has already answered (REPEAT) versus a genuinely new one (NEW)?

    python -m omega.bench.memory_bench --out results.json [--model qwen2.5:1.5b ...]

Systems
    baseline_exact   normalized string equality with an earlier question
                     (what a naive "don't send the same text twice" check does)
    omega_rules      the shipped deterministic RelationshipMemory.check_draft
                     (REPEATED_QUESTION), run against a real node holding the
                     conversation
    llm:<model>      a local Ollama model asked YES/NO with the answered
                     questions in the prompt (temperature 0, seed 0)
    rules_or_llm:<m> flag if either omega_rules or the model flags

The case file is hashed into the result, so a score cannot silently follow
an edited dataset. Every per-case prediction is recorded.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from omega.canonical import sha256_hex  # noqa: E402
from omega.relationship import RelationshipMemory, normalize  # noqa: E402
from omega.store import Node  # noqa: E402

CASES = Path(__file__).with_name("memory_cases.json")

PROMPT = """You check a draft message before it is sent to {contact}.
Questions we already asked {contact}, with {contact}'s answers:
{qa}

New question in the draft: "{q}"

Does the new question ask for information {contact} has ALREADY given in the answers above?
Reply with exactly one word: YES or NO."""


def load():
    raw = CASES.read_bytes()
    return json.loads(raw), sha256_hex(raw)


def baseline_exact(data):
    asked = {normalize(x["q"]) for x in data["answered"]}
    return {c["id"]: ("REPEAT" if normalize(c["q"]) in asked else "NEW", 0) for c in data["cases"]}


def omega_rules(data):
    with tempfile.TemporaryDirectory() as d:
        n = Node.init(Path(d) / "n", "bench")
        rm = RelationshipMemory(n)
        cid = rm.add_contact(data["contact"], primary="bench:contact", actor="human:bench")
        t0 = 1793534400
        for i, x in enumerate(data["answered"]):
            ts = lambda k: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 + k))  # noqa: E731
            rm.record_message(cid, direction="OUT", text=f"Hi Dana, {x['q']}", sent_at=ts(2 * i * 60),
                              source_ref=f"bench:out/{i}", actor="human:bench")
            rm.record_message(cid, direction="IN", text=x["a"], sent_at=ts((2 * i + 1) * 60),
                              source_ref=f"bench:in/{i}", actor="tool:bench")
        out = {}
        for c in data["cases"]:
            t = time.perf_counter()
            f = rm.check_draft(cid, f"Hi Dana, {c['q']}")
            ms = int((time.perf_counter() - t) * 1000)
            out[c["id"]] = ("REPEAT" if any(x["code"] == "REPEATED_QUESTION" for x in f) else "NEW", ms)
        n.close()
    return out


def llm(data, client, model):
    qa = "\n".join(f'- Q: "{x["q"]}"  A: "{x["a"]}"' for x in data["answered"])
    out = {}
    for c in data["cases"]:
        t = time.perf_counter()
        ans = client.generate(model, PROMPT.format(contact=data["contact"], qa=qa, q=c["q"]))
        ms = int((time.perf_counter() - t) * 1000)
        word = ans.strip().split()[0].strip(".,!").upper() if ans.strip() else ""
        out[c["id"]] = ("REPEAT" if word == "YES" else "NEW", ms, ans.strip()[:80])
    return out


def score(data, preds):
    def m(cases):
        tp = sum(preds[c["id"]][0] == "REPEAT" and c["label"] == "REPEAT" for c in cases)
        fp = sum(preds[c["id"]][0] == "REPEAT" and c["label"] == "NEW" for c in cases)
        fn = sum(preds[c["id"]][0] == "NEW" and c["label"] == "REPEAT" for c in cases)
        tn = sum(preds[c["id"]][0] == "NEW" and c["label"] == "NEW" for c in cases)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
        r = lambda x: None if x is None else round(x, 3)  # noqa: E731
        return {"n": len(cases), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "accuracy": r((tp + tn) / len(cases)),
                "precision": r(prec), "recall": r(rec), "f1": r(f1)}
    by_kind = {k: m([c for c in data["cases"] if c["kind"] == k]) for k in ("exact", "paraphrase", "near_miss", "new")}
    lat = [p[1] for p in preds.values()]
    return {"overall": m(data["cases"]), "by_kind": by_kind,
            "latency_ms": {"median": int(statistics.median(lat)), "max": max(lat)},
            "errors": sorted(c["id"] for c in data["cases"] if preds[c["id"]][0] != c["label"])}


def record_as_benchmark(node, result: dict, hw: dict) -> list:
    """Write each llm:<model> score as a BENCHMARK_RESULT (task_class
    repeat_detection, score = F1 per-mille) so ModelRouter can route on it."""
    from omega.forge import BENCH_ACTOR
    evs = []
    for name, v in sorted(result["systems"].items()):
        if not name.startswith("llm:"):
            continue
        f1 = v["overall"]["f1"] or 0.0
        evs.append(node.append("BENCHMARK_RESULT",
                               {"model": name[4:], "task_class": "repeat_detection",
                                "suite_digest": "mb_" + result["cases_sha256"][:32],
                                "score_permille": int(round(f1 * 1000)), "latency_ms": v["latency_ms"]["median"],
                                "cases": result["cases"], "hardware_class": hw["hardware_class"]},
                               actor=BENCH_ACTOR, privacy="INTERNAL",
                               provenance=[{"kind": "tool", "ref": f"omega.bench.memory_bench:{result['cases_sha256'][:16]}"}]))
    return evs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", action="append", default=[])
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    a = ap.parse_args(argv)
    data, sha = load()
    result = {"schema": "fw.omega.memory-bench-result/1", "cases_sha256": sha, "cases": len(data["cases"]),
              "labels": {"REPEAT": sum(c["label"] == "REPEAT" for c in data["cases"]),
                         "NEW": sum(c["label"] == "NEW" for c in data["cases"])},
              "host": {"platform": platform.platform(), "python": platform.python_version(),
                       "machine": platform.machine()},
              "systems": {}, "predictions": {}}
    runs = {"baseline_exact": baseline_exact(data), "omega_rules": omega_rules(data)}
    if a.model:
        from omega.forge import OllamaClient
        client = OllamaClient(a.ollama, timeout=300)
        tags = client._req("/api/tags")["models"]
        result["ollama"] = {"version": client._req("/api/version").get("version"),
                            "models": {m["name"]: {"digest": m["digest"], "size": m["size"]} for m in tags}}
        for model in a.model:
            client.generate(model, "Reply OK.")   # warm-up load, not timed
            lp = llm(data, client, model)
            runs[f"llm:{model}"] = lp
            runs[f"rules_or_llm:{model}"] = {k: ("REPEAT" if "REPEAT" in (runs["omega_rules"][k][0], lp[k][0]) else "NEW",
                                                 lp[k][1]) for k in lp}
    for name, preds in runs.items():
        result["systems"][name] = score(data, preds)
        result["predictions"][name] = {k: list(v) for k, v in sorted(preds.items())}
    Path(a.out).write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({k: {"overall": v["overall"], "paraphrase_recall": v["by_kind"]["paraphrase"]["recall"],
                          "near_miss_fp": v["by_kind"]["near_miss"]["fp"], "median_ms": v["latency_ms"]["median"]}
                      for k, v in result["systems"].items()}, indent=1))


if __name__ == "__main__":
    main()
