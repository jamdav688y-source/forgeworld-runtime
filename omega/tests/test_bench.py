"""Memory benchmark: the frozen dataset, reproducible deterministic scores,
benchmark-driven routing, and (when a local Ollama is running) a real
model-backed advisory check."""
import os

import pytest

from omega import forge
from omega.bench import memory_bench
from omega.relationship import RelationshipMemory
from omega.tests.conftest import HUMAN

FROZEN_SHA256 = "d9429aee1be4bf8aaeb185bf33b37affc6cef466ca46ebbac2581d820e63f1a0"


def test_dataset_is_frozen():
    data, sha = memory_bench.load()
    assert sha == FROZEN_SHA256, "the case file changed: re-run every system and update BENCHMARK_REPORT.md"
    assert (len(data["cases"]), sum(c["label"] == "REPEAT" for c in data["cases"])) == (50, 31)


def test_deterministic_systems_reproduce_reported_scores():
    data, _ = memory_bench.load()
    base = memory_bench.score(data, memory_bench.baseline_exact(data))
    rules = memory_bench.score(data, memory_bench.omega_rules(data))
    assert (base["overall"]["tp"], base["overall"]["fp"], base["overall"]["fn"]) == (10, 0, 21)
    assert (rules["overall"]["tp"], rules["overall"]["fp"], rules["overall"]["fn"]) == (17, 2, 14)
    assert rules["by_kind"]["exact"]["recall"] == 1.0 and rules["by_kind"]["new"]["fp"] == 0


def test_router_uses_repeat_detection_evidence(pc):
    result = {"cases_sha256": FROZEN_SHA256, "cases": 50, "systems": {
        "llm:big-but-bad": {"overall": {"f1": 0.171}, "latency_ms": {"median": 300}},
        "llm:small-good": {"overall": {"f1": 0.836}, "latency_ms": {"median": 340}},
        "omega_rules": {"overall": {"f1": 0.68}, "latency_ms": {"median": 2}}}}
    evs = memory_bench.record_as_benchmark(pc, result, {"hardware_class": "hw-x"})
    assert len(evs) == 2
    r = forge.ModelRouter(pc).select("repeat_detection", hardware_class="hw-x")
    assert r["selected"] == "small-good"


def _ollama_model():
    c = forge.OllamaClient(os.environ.get("OMEGA_OLLAMA", "http://127.0.0.1:11434"), timeout=120)
    if not c.available():
        return None, None
    want = os.environ.get("OMEGA_OLLAMA_MODEL", "qwen2.5:1.5b")
    return (c, want) if want in c.models() else (None, None)


@pytest.mark.skipif(_ollama_model()[0] is None, reason="no local Ollama with the test model")
def test_real_local_model_adds_advisory_warning(phone):
    client, model = _ollama_model()
    rm = RelationshipMemory(phone)
    c = rm.add_contact("Dana Reyes", primary="sms:+15550100", actor=HUMAN)
    rm.record_message(c, direction="OUT", text="Hi Dana, what budget do you have in mind?",
                      sent_at="2026-11-01T10:00:00Z", source_ref="sms:1", actor=HUMAN)
    rm.record_message(c, direction="IN", text="Around $5,000 for phase one.", sent_at="2026-11-01T10:05:00Z",
                      source_ref="sms:2", actor="tool:import")
    draft = "Hi Dana, how much were you planning to spend on this?"
    rules_only = rm.check_draft(c, draft)
    assert "REPEATED_QUESTION" not in {f["code"] for f in rules_only}          # the rules miss this paraphrase
    f = rm.check_draft(c, draft, semantic_checker=client.repeat_checker(model, "Dana"))
    hit = [x for x in f if x["code"] == "POSSIBLE_REPEAT"]
    assert hit and hit[0]["severity"] == "WARN" and hit[0]["checker"] == f"ollama:{model}"
