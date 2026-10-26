#!/usr/bin/env python3
"""Deterministic Mission Router.

Routes a mission to a capability (not a brand). Every decision separates
confidence into four independent measurements (reachability, task-fit,
output quality, historical evidence) and cost into five independent
measurements (dollar, latency, tokens, attention, execution complexity),
then exposes the full reasoning: selected capability, alternatives
considered, evidence, tradeoffs, confidence, and expected outcome.

This is deterministic by design: same inputs + same registry/history state
always produce the same decision. Adaptive re-weighting (ROUTER_V2) is a
separate, later layer that may only recommend changes here once it has
validated execution evidence to justify them -- it never edits this scoring
directly.
"""
import argparse
import json
import sys
import time
from pathlib import Path

CAPABILITIES_DIR = Path(__file__).resolve().parent.parent / "capabilities"
ROUTER_DIR = Path(__file__).resolve().parent
HISTORY_PATH = CAPABILITIES_DIR / "history.jsonl"
DECISIONS_PATH = ROUTER_DIR / "decisions.jsonl"

sys.path.insert(0, str(CAPABILITIES_DIR))
sys.path.insert(0, str(ROUTER_DIR))
import discover  # noqa: E402
import architecture_router  # noqa: E402

CONFIDENCE_WEIGHTS = {
    "reachability": 0.35,
    "task_fit": 0.30,
    "output_quality": 0.20,
    "historical_evidence": 0.15,
}
COST_PENALTY_WEIGHT = 0.3
COST_AXES = ("dollar", "latency", "tokens", "attention", "complexity")


def load_registry():
    return discover.load_registry()


def load_history():
    if not HISTORY_PATH.exists():
        return []
    records = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def mission_class(required_tags):
    return "+".join(sorted(required_tags)) if required_tags else "general"


def historical_stats(capability_id, cls, history):
    matches = [
        r["success_score"]
        for r in history
        if r["capability_id"] == capability_id and r["mission_class"] == cls
    ]
    if not matches:
        return 0.5, 0, True  # neutral prior, no evidence yet
    return sum(matches) / len(matches), len(matches), False


def task_fit(cap_tags, required_tags):
    if not required_tags:
        return 0.5
    overlap = len(set(cap_tags) & set(required_tags))
    return overlap / len(required_tags)


def cost_score(cost):
    return sum(cost[axis] for axis in COST_AXES) / len(COST_AXES)


def score_capability(cap, required_tags, reachability_state, history):
    cls = mission_class(required_tags)
    reach = reachability_state.get(cap["id"], {})
    reachability_confidence = reach.get("reachability_confidence", 0.0)
    fit = task_fit(cap["tags"], required_tags)
    quality, n_records, no_evidence = historical_stats(cap["id"], cls, history)
    hist_confidence = min(1.0, n_records / 5)

    confidence = (
        CONFIDENCE_WEIGHTS["reachability"] * reachability_confidence
        + CONFIDENCE_WEIGHTS["task_fit"] * fit
        + CONFIDENCE_WEIGHTS["output_quality"] * quality
        + CONFIDENCE_WEIGHTS["historical_evidence"] * hist_confidence
    )
    cost = cost_score(cap["cost"])
    routing_score = max(0.0, min(1.0, confidence - COST_PENALTY_WEIGHT * cost))

    return {
        "capability_id": cap["id"],
        "reachable": reachability_confidence > 0.0,
        "routing_score": round(routing_score, 4),
        "confidence": {
            "overall": round(confidence, 4),
            "reachability": round(reachability_confidence, 4),
            "task_fit": round(fit, 4),
            "output_quality": round(quality, 4),
            "output_quality_no_evidence": no_evidence,
            "historical_evidence": round(hist_confidence, 4),
            "historical_record_count": n_records,
        },
        "cost": {
            **cap["cost"],
            "composite": round(cost, 4),
        },
        "reachability_evidence": reach.get("evidence", "not probed"),
    }


def build_tradeoff(selected, runner_up):
    if runner_up is None:
        return "No viable alternative was available for comparison."
    axes = ["reachability", "task_fit", "output_quality", "historical_evidence"]
    biggest_axis = max(
        axes,
        key=lambda a: selected["confidence"][a] - runner_up["confidence"][a],
    )
    delta = round(
        selected["confidence"][biggest_axis] - runner_up["confidence"][biggest_axis], 4
    )
    return (
        f"Selected '{selected['capability_id']}' over '{runner_up['capability_id']}' "
        f"primarily on {biggest_axis} (+{delta}); cost composite "
        f"{selected['cost']['composite']} vs {runner_up['cost']['composite']}."
    )


def route(objective, required_tags, mission_id=None, architecture_context=None):
    registry = load_registry()
    reachability_state = discover.probe_all()
    discover.write_state(reachability_state)
    history = load_history()
    architecture_assessment = (
        architecture_router.assess_architecture(
            architecture_router.MissionArchitectureContext(**architecture_context)
        )
        if architecture_context is not None
        else {
            "status": "not_assessed_missing_context",
            "execution_authorized": False,
            "principle": "least_complex_safe_architecture",
        }
    )

    scored = [
        score_capability(cap, required_tags, reachability_state, history)
        for cap in registry
    ]
    scored.sort(key=lambda s: (s["reachable"], s["routing_score"]), reverse=True)

    reachable_scored = [s for s in scored if s["reachable"]]
    status = "routed" if reachable_scored else "queued_no_reachable_capability"
    selected = reachable_scored[0] if reachable_scored else None
    runner_up = None
    if selected is not None:
        remaining = [s for s in scored if s["capability_id"] != selected["capability_id"]]
        runner_up = remaining[0] if remaining else None

    decision = {
        "mission_id": mission_id or f"M-{int(time.time())}",
        "objective": objective,
        "required_tags": required_tags,
        "mission_class": mission_class(required_tags),
        "architecture_assessment": architecture_assessment,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "selected_capability": selected["capability_id"] if selected else None,
        "alternatives_considered": [s for s in scored if not selected or s["capability_id"] != selected["capability_id"]],
        "selected_detail": selected,
        "tradeoffs": build_tradeoff(selected, runner_up) if selected else (
            "No reachable capability could be scored; mission queued per Failure Law."
        ),
        "expected_outcome": (
            f"Route '{objective}' to {selected['capability_id']} "
            f"(confidence {selected['confidence']['overall']}, cost {selected['cost']['composite']}); "
            f"based on {selected['confidence']['historical_record_count']} historical record(s) for this mission class."
            if selected else
            f"No reachable capability for required tags {required_tags}. "
            "Mission queued; operator notification required per Failure Law."
        ),
        "provider_actually_used": None,
        "artifacts": None,
        "validation": None,
        "commercial_outcome": None,
        "knowledge_contribution": None,
        "future_recommendations": None,
    }

    with open(DECISIONS_PATH, "a") as f:
        f.write(json.dumps(decision) + "\n")

    return decision


def main():
    parser = argparse.ArgumentParser(description="Route a mission to a capability.")
    parser.add_argument("--objective", required=True, help="What the mission is trying to accomplish.")
    parser.add_argument("--tags", default="", help="Comma-separated required capability tags.")
    parser.add_argument("--mission-id", default=None)
    parser.add_argument("--grounding-required", action="store_true")
    parser.add_argument("--tool-actions", action="store_true")
    parser.add_argument("--persistent-memory", action="store_true")
    parser.add_argument("--parallel-specialists", action="store_true")
    parser.add_argument("--event-triggered", action="store_true")
    parser.add_argument("--self-correction", action="store_true")
    parser.add_argument("--consequential-actions", action="store_true")
    parser.add_argument("--regulated-or-sensitive", action="store_true")
    parser.add_argument("--multi-tenant", action="store_true")
    parser.add_argument("--enterprise-scale", action="store_true")
    parser.add_argument("--risk", choices=["low", "medium", "high", "critical"], default="low")
    parser.add_argument(
        "--evidence-level",
        choices=["none", "hypothesis", "prototype", "validated", "operational"],
        default="none",
    )
    parser.add_argument("--requested-level", type=int, choices=range(1, 7), default=None)
    parser.add_argument(
        "--controls",
        default="",
        help="Comma-separated controls such as human_approval,validation,recovery.",
    )
    args = parser.parse_args()

    required_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    architecture_context = {
        "grounding_required": args.grounding_required,
        "tool_actions": args.tool_actions,
        "persistent_memory": args.persistent_memory,
        "parallel_specialists": args.parallel_specialists,
        "event_triggered": args.event_triggered,
        "self_correction": args.self_correction,
        "consequential_actions": args.consequential_actions,
        "regulated_or_sensitive": args.regulated_or_sensitive,
        "multi_tenant": args.multi_tenant,
        "enterprise_scale": args.enterprise_scale,
        "risk": args.risk,
        "evidence_level": args.evidence_level,
        "requested_level": args.requested_level,
        "controls": [c.strip() for c in args.controls.split(",") if c.strip()],
    }
    decision = route(
        args.objective,
        required_tags,
        args.mission_id,
        architecture_context=architecture_context,
    )
    json.dump(decision, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
