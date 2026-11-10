"""Offline operation of both nodes (1, 2) and the forge substrate: Ollama
client, benchmark-driven model routing, graceful degradation."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from omega import diagnostics, forge
from omega.commercial import CommercialLedger
from omega.demo_e2e import no_network
from omega.relationship import RelationshipMemory
from omega.tasks import Executor, TaskQueue
from omega.tests.conftest import HUMAN


def test_pocket_node_fully_functional_with_no_network(phone):
    with no_network():
        with pytest.raises(OSError):
            socket.socket()
        rm = RelationshipMemory(phone)
        c = rm.add_contact("Ana Silva", primary="sms:+15550123", actor=HUMAN)
        rm.record_message(c, direction="OUT", text="Hi Ana, when do you need the site live?",
                          sent_at="2026-11-01T09:00:00Z", source_ref="sms:a#1", actor=HUMAN)
        rm.record_message(c, direction="IN", text="By end of January please.", sent_at="2026-11-01T09:10:00Z",
                          source_ref="sms:a#2", actor="tool:sms-import")
        assert rm.context(c)["facts"]["timeline"]["value"] == "end of January"
        assert phone.search("January")
        d = rm.compose(c, "proposal")
        assert "timeline" not in (d["next_question"] or "")
        CommercialLedger(phone).record("d1", "INTEREST_EXPRESSED", "wants a site", actor=HUMAN, source_ref="sms:a#1")
        q = TaskQueue(phone, {"reindex": Executor(lambda a: "ok")})
        t = q.queue("reindex", {}, actor=HUMAN, external_effect=False)
        assert dict(q.run_once())[t] == "SUCCEEDED"
        rep = diagnostics.report(phone)
        assert rep["integrity"]["ok"] and rep["capabilities"]["ollama"] == "NOT_PROBED"
        assert "Ana" not in json.dumps(rep)   # diagnostics carry no payload text


def test_forge_node_degrades_when_ollama_is_unavailable(pc):
    client = forge.OllamaClient("http://127.0.0.1:9", timeout=0.5)   # nothing listens on port 9
    assert client.available() is False
    route = forge.ModelRouter(pc).select("drafting")
    assert route["selected"] is None and route["fallback"] == "deterministic"
    rm = RelationshipMemory(pc)
    c = rm.add_contact("Ana Silva", primary="sms:+15550123", actor=HUMAN)
    d = rm.compose(c, "discovery", generator=client.drafter("any-model"))
    assert d["generator"] == "deterministic-template"
    assert "unavailable" in d["generator_rejected"]["reason"]


def test_non_loopback_model_endpoint_requires_authorization():
    with pytest.raises(PermissionError):
        forge.OllamaClient("http://203.0.113.5:11434")
    forge.OllamaClient("http://203.0.113.5:11434", allow_remote=True)  # explicit operator choice


class FakeOllama(BaseHTTPRequestHandler):
    """Two installed models. The LARGE one is slow and wrong; the small one is
    right. A size-based router would pick the wrong one."""
    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "giant:70b"}, {"name": "nimble:3b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p = body["prompt"]
        if body["model"] == "giant:70b":
            time.sleep(0.03)
            drafting = "follow-up" in p or "message to" in p
            ans = "It depends. What is your budget?" if drafting else "unclear"
        else:
            ans = ("Hi Dana, thanks! What timeline are you working towards?" if ("follow-up" in p or "message to" in p)
                   else "$5,000" if "$5,000" in p else "5k")
        self._send({"response": ans})


@pytest.fixture
def fake_ollama():
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_router_selects_by_recorded_benchmark_not_size(pc, fake_ollama):
    client = forge.OllamaClient(fake_ollama, timeout=5)
    assert client.models() == ["giant:70b", "nimble:3b"]
    hw = {"hardware_class": "test-hw"}
    evs = forge.run_benchmark(pc, client, client.models(), hw=hw)
    scores = {(e.payload["model"], e.payload["task_class"]): e.payload["score_permille"] for e in evs}
    assert scores[("nimble:3b", "extraction")] == 1000 and scores[("giant:70b", "extraction")] == 0
    assert scores[("nimble:3b", "drafting")] == 1000 and scores[("giant:70b", "drafting")] == 0
    r = forge.ModelRouter(pc).select("extraction", hardware_class="test-hw")
    assert r["selected"] == "nimble:3b" and r["evidence"].startswith("ev_")
    assert {c["model"]: c["excluded"] for c in r["candidates"]}["giant:70b"] == "BELOW_QUALITY_BAR"
    # evidence from other hardware is not transferable
    assert forge.ModelRouter(pc).select("extraction", hardware_class="other-hw")["selected"] is None
    # a model that is not installed any more is not selected
    assert forge.ModelRouter(pc).select("extraction", hardware_class="test-hw", available=["giant:70b"])["selected"] is None


def test_local_model_drafts_are_used_only_when_they_pass_checks(pc, fake_ollama):
    client = forge.OllamaClient(fake_ollama, timeout=5)
    rm = RelationshipMemory(pc)
    c = rm.add_contact("Dana Reyes", primary="sms:+1555", actor=HUMAN)
    rm.assert_fact(c, "budget", "$5,000", basis="OPERATOR", actor=HUMAN)
    good, bad = client.drafter("nimble:3b"), client.drafter("giant:70b")
    d = rm.compose(c, "discovery", generator=good)
    assert d["generator"] == "ollama:nimble:3b"
    d = rm.compose(c, "discovery", generator=bad)
    assert d["generator"] == "deterministic-template" and d["generator_rejected"]["codes"] == ["REPEATED_QUESTION"]


def test_hardware_profile_and_repository_analysis(tmp_path):
    hw = forge.hardware_profile()
    assert hw["cpus"] >= 1 and hw["hardware_class"]
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "c.txt").write_text("rule")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "test_x.py").write_text("")
    a = forge.analyze_repository(tmp_path)
    assert a["test_files"] == ["pkg/test_x.py"] and a["governance_digest"].startswith("gv_")
