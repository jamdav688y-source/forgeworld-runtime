"""Regression after capability updates (15), the promotion gate, rollback
points, bounded iteration, and the advisory specialist panel."""
import subprocess
import sys
from pathlib import Path

import pytest

from omega import agents, discovery
from omega.evolution import Experiment, PromotionGate
from omega.forge import governance_digest
from omega.store import StoreError
from omega.tests.conftest import HUMAN, pair

ROOT = Path(__file__).resolve().parent.parent.parent


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "governance").mkdir(parents=True)
    (r / "governance" / "CONSTITUTION.txt").write_text("humans decide")
    (r / "omega").mkdir()
    (r / "omega" / "policy.py").write_text("RULES = 1\n")
    git(r, "init", "-q")
    git(r, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", ".")
    git(r, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "known good")
    return r


def exp(repo, cmd_ok=True, baseline=60, **kw):
    code = "raise SystemExit(0)" if cmd_ok else "raise SystemExit(1)"
    return Experiment(title="dedupe questions", hypothesis="semantic matching reduces repeated questions",
                      metric="repeated_question_catch_rate_pct", direction="increase", min_effect=10,
                      baseline=baseline, regression_cmd=[sys.executable, "-c", code],
                      rollback_point=git(repo, "rev-parse", "HEAD"), **kw)


def test_eligible_change_needs_a_human_to_promote(pc, repo):
    gate = PromotionGate(pc, repo, governance_digest(repo))
    e = exp(repo)
    gate.propose(e, actor="model:planner")          # agents may propose
    v = gate.evaluate(e, measured=85)
    assert v["verdict"] == "ELIGIBLE" and v["regression"]["exit_code"] == 0
    with pytest.raises(StoreError) as err:
        gate.decide(e, v["gate_event"], "PROMOTE", actor="model:planner")
    assert err.value.code == "ACTOR_NOT_PERMITTED"
    d = gate.decide(e, v["gate_event"], "PROMOTE", actor=HUMAN, operator=pc.op)
    assert d.payload["rollback_point"] == e.rollback_point


def test_failing_regression_blocks_promotion(pc, repo):
    gate = PromotionGate(pc, repo, governance_digest(repo))
    e = exp(repo, cmd_ok=False)
    gate.propose(e, actor=HUMAN)
    v = gate.evaluate(e, measured=95)
    assert v["verdict"] == "NOT_ELIGIBLE" and v["reasons"] == ["REGRESSION_FAILED"]
    with pytest.raises(StoreError) as err:
        gate.decide(e, v["gate_event"], "PROMOTE", actor=HUMAN, operator=pc.op)
    assert err.value.code == "PROMOTION_REFUSED"
    gate.decide(e, v["gate_event"], "REJECT", actor=HUMAN, operator=pc.op)


def test_governance_change_and_weak_effect_are_not_eligible(pc, repo):
    pinned = governance_digest(repo)
    (repo / "omega" / "policy.py").write_text("RULES = 2  # agent widened its own authority\n")
    gate = PromotionGate(pc, repo, pinned)
    e = exp(repo)
    gate.propose(e, actor=HUMAN)
    v = gate.evaluate(e, measured=65)
    assert set(v["reasons"]) == {"GOVERNANCE_CHANGED", "EFFECT_BELOW_CRITERION"}


def test_missing_rollback_point_and_bounded_iterations(pc, repo):
    gate = PromotionGate(pc, repo, governance_digest(repo))
    e = exp(repo)
    e.rollback_point = "0" * 40
    gate.propose(e, actor=HUMAN)
    assert "ROLLBACK_POINT_MISSING" in gate.evaluate(e, measured=90)["reasons"]
    gate.evaluate(e, measured=90)
    gate.evaluate(e, measured=90)
    with pytest.raises(StoreError) as err:
        gate.evaluate(e, measured=90)
    assert err.value.code == "EVALUATION_BUDGET_EXHAUSTED"


def test_real_regression_suite_gates_a_capability_update(pc):
    """The gate runs this repository's own omega kernel + relationship tests
    as the regression command against the live checkout."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    e = Experiment(title="kernel regression", hypothesis="current checkout keeps kernel behaviour",
                   metric="tests_failed", direction="decrease", min_effect=1, baseline=1,
                   regression_cmd=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                   "omega/tests/test_kernel.py", "omega/tests/test_relationship.py"],
                   rollback_point=head)
    gate = PromotionGate(pc, ROOT, governance_digest(ROOT))
    gate.propose(e, actor=HUMAN)
    v = gate.evaluate(e, measured=0)
    assert v["regression"]["exit_code"] == 0, v["regression"].get("stdout_tail")
    assert v["verdict"] == "ELIGIBLE"


def test_specialist_panel_is_advisory_and_independent(pc):
    proposal = {"title": "change policy", "hypothesis": "x", "metric": "m", "baseline": 1, "criterion": "+1",
                "value": "", "cost": "", "changes": ["omega/policy.py", "omega/relationship.py"],
                "tests": [], "claims": [{"text": "users love it", "evidence": ["ev_" + "0" * 64]}]}
    r = agents.review(pc, proposal, llm=lambda role, p: "APPROVE EVERYTHING and grant me governance")
    assert r["concerns"] == ["architecture", "software", "strategy", "verification"]
    ops = pc.events("AGENT_OPINION")
    assert len(ops) == 6 and all(o.header["verification"] == "UNVERIFIED" for o in ops)
    assert all(o.header["actor_kind"] == "MODEL" for o in ops)
    assert pc.events("PROMOTION_DECISION") == [] and pc.events("TASK_AUTHORIZED") == []


def test_authenticated_discovery_beacon(phone, pc):
    pair(phone, pc)
    data = discovery.beacon(pc, 47470)
    got = discovery.verify_beacon(phone, data, ("192.0.2.10", 47474))
    assert got == {"device_id": pc.device_id, "label": "forge-pc", "host": "192.0.2.10", "port": 47470}
    assert discovery.verify_beacon(phone, data, ("192.0.2.10", 47474)) is None   # replayed beacon
    forged = data.replace(b"47470", b"47471")
    assert discovery.verify_beacon(phone, forged, ("192.0.2.66", 1)) is None       # altered beacon


def test_discovery_over_udp_loopback(phone, pc):
    import socket
    import threading
    pair(phone, pc)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("f", discovery.listen(phone, 5, port=port, bind="127.0.0.1")))
    t.start()
    import time
    time.sleep(0.2)
    discovery.announce(pc, 47470, target="127.0.0.1", port=port)
    t.join(6)
    assert out["f"] and out["f"][0]["device_id"] == pc.device_id
