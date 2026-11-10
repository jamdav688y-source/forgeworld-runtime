"""Bounded evolution: experiments, a promotion gate, rollback points (Stages H, J).

    Experience -> Observation -> Hypothesis -> Experiment -> Evidence ->
    Decision -> Capability -> Measured value -> New experience

    propose()   EXPERIMENT_RECORDED(PROPOSED): falsifiable hypothesis, one
                metric, direction, minimum effect, baseline, regression command,
                known-good rollback point (a git commit that must exist)
    evaluate()  runs the regression command for real (subprocess), measures
                the governance digest, checks the criterion, and records
                EXPERIMENT_RECORDED(MEASURED) with verdict ELIGIBLE /
                NOT_ELIGIBLE and every reason
    decide()    PROMOTION_DECISION -- HUMAN ONLY (policy.EVENT_TYPES), and a
                PROMOTE is refused unless the cited gate verdict is ELIGIBLE

What this module does NOT do: it never edits code, never merges, never
loops. There is no autonomous self-modification path: an agent may propose
and the gate may measure, but only a human decision event changes status,
and promotion itself (checking out / merging the candidate) is an operator
action outside this module. A candidate that changes any governance path
(GOVERNANCE_PATHS) is NOT_ELIGIBLE by construction: governance changes are
made by humans through review, not through the evolution loop.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from omega.canonical import digest
from omega.events import event_id_for
from omega.store import StoreError

GOVERNANCE_PATHS = ("governance", "omega/policy.py", "omega/events.py", "omega/evolution.py", "omega/tasks.py")
GATE_ACTOR = "tool:omega-promotion-gate"
MAX_EVALUATIONS_PER_EXPERIMENT = 3


@dataclass
class Experiment:
    title: str
    hypothesis: str
    metric: str
    direction: str            # "increase" | "decrease"
    min_effect: int           # integer units of the metric
    baseline: int
    regression_cmd: list
    rollback_point: str       # git commit id of the known-good state
    candidate_ref: str = ""   # git commit / branch of the candidate
    evaluation_criteria: list = field(default_factory=list)

    @property
    def experiment_id(self) -> str:
        return "xp_" + digest("experiment", [self.title, self.hypothesis, self.metric, self.direction,
                                             self.min_effect, self.baseline, self.rollback_point,
                                             self.candidate_ref])[:24]


class PromotionGate:
    def __init__(self, node, repo_root, pinned_governance_digest: str):
        self.node = node
        self.root = repo_root
        self.pinned = pinned_governance_digest

    def propose(self, exp: Experiment, *, actor: str):
        if exp.direction not in ("increase", "decrease") or exp.min_effect < 1:
            raise StoreError("EXPERIMENT_INVALID", "direction must be increase|decrease and min_effect >= 1")
        return self.node.append("EXPERIMENT_RECORDED", {"experiment_id": exp.experiment_id, "phase": "PROPOSED",
                                                        "hypothesis": exp.hypothesis, "metric": exp.metric,
                                                        "spec": asdict(exp)},
                                actor=actor, privacy="INTERNAL", links=[f"experiment:{exp.experiment_id}"],
                                provenance=[{"kind": "source", "ref": f"git:{exp.rollback_point}"}])

    def evaluate(self, exp: Experiment, measured: int) -> dict:
        from omega.forge import governance_digest, run_command
        xid = exp.experiment_id
        prior = [e for e in self.node.events("EXPERIMENT_RECORDED", f"experiment:{xid}") if e.payload]
        proposed = [e for e in prior if e.payload["phase"] == "PROPOSED"]
        if not proposed:
            raise StoreError("EXPERIMENT_UNKNOWN", "propose() first")
        if sum(e.payload["phase"] == "MEASURED" for e in prior) >= MAX_EVALUATIONS_PER_EXPERIMENT:
            raise StoreError("EVALUATION_BUDGET_EXHAUSTED", "bounded iteration: a human must decide or re-propose")
        reasons = []
        reg = run_command(exp.regression_cmd, self.root)
        if reg.get("exit_code") != 0:
            reasons.append("REGRESSION_FAILED")
        gov = governance_digest(self.root)
        if gov != self.pinned:
            reasons.append("GOVERNANCE_CHANGED")
        rb = run_command(["git", "cat-file", "-e", f"{exp.rollback_point}^{{commit}}"], self.root, timeout=20)
        if rb.get("exit_code") != 0:
            reasons.append("ROLLBACK_POINT_MISSING")
        delta = measured - exp.baseline if exp.direction == "increase" else exp.baseline - measured
        if delta < exp.min_effect:
            reasons.append("EFFECT_BELOW_CRITERION")
        verdict = "ELIGIBLE" if not reasons else "NOT_ELIGIBLE"
        ev = self.node.append("EXPERIMENT_RECORDED",
                              {"experiment_id": xid, "phase": "MEASURED", "hypothesis": exp.hypothesis,
                               "metric": exp.metric, "baseline": exp.baseline, "measured": measured, "delta": delta,
                               "verdict": verdict, "reasons": reasons,
                               "regression": {"cmd": reg["cmd"], "exit_code": reg.get("exit_code"),
                                              "stdout_sha256": reg.get("stdout_sha256", "")},
                               "governance_digest": gov, "pinned_governance_digest": self.pinned},
                              actor=GATE_ACTOR, privacy="INTERNAL", links=[f"experiment:{xid}"],
                              parents=[event_id_for(proposed[-1].header)],
                              provenance=[{"kind": "tool", "ref": " ".join(map(str, exp.regression_cmd))}])
        return {"experiment_id": xid, "verdict": verdict, "reasons": reasons, "gate_event": event_id_for(ev.header),
                "regression": reg}

    def decide(self, exp: Experiment, gate_event: str, decision: str, *, actor: str, note: str = "", operator=None):
        gate = self.node.get(gate_event)
        if gate is None or gate.payload is None or gate.payload.get("experiment_id") != exp.experiment_id \
                or gate.payload.get("phase") != "MEASURED":
            raise StoreError("GATE_EVENT_INVALID", gate_event)
        if decision == "PROMOTE" and gate.payload["verdict"] != "ELIGIBLE":
            raise StoreError("PROMOTION_REFUSED", f"gate verdict {gate.payload['verdict']}: {gate.payload['reasons']}")
        return self.node.append("PROMOTION_DECISION",
                                {"experiment_id": exp.experiment_id, "decision": decision,
                                 "rollback_point": exp.rollback_point, "gate_event": gate_event,
                                 "note": note or "operator decision"},
                                actor=actor, privacy="INTERNAL", links=[f"experiment:{exp.experiment_id}"],
                                parents=[gate_event], verification="VERIFIED" if decision == "PROMOTE" else "UNVERIFIED",
                                operator=operator)
