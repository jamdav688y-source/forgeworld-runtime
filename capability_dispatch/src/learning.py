"""DISPATCH LEARNING RECORD -- extends router/record_outcome.py's
existing, single sanctioned write path into capabilities/history.jsonl.

record_outcome.record()'s schema (capability_id, mission_class,
success_score, notes) is load-bearing for router/mission_router.py's
historical_stats(), which already reads capabilities/history.jsonl back
on every route() call. Widening those 4 fields in place would risk
breaking that reader, so this module does not touch record_outcome.py --
it computes the mission's richer DispatchLearningRecord fields
(predicted-vs-observed utility/cost/latency, failure classification,
rollback result, evidence sufficiency) and folds the detail into a single
JSON-encoded `notes` string, calling record_outcome.record() directly for
the write itself. Anything that only reads success_score/mission_class
(mission_router.py today) is unaffected; anything that wants the richer
detail later can json.loads(notes).

Historical records feed back into router.mission_router.route()'s
historical_stats() automatically -- no new read path is introduced.
"""
import json

from router import record_outcome

from . import schema
from .common import now_iso


def _clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def compute_success_score(learning_record: dict) -> float:
    """Deterministic function of predicted-vs-observed utility/cost/latency
    and rollback/failure state -- not a subjective guess. Perfect
    agreement between predicted and observed utility, cost, and latency
    with no failure/rollback yields 1.0; any failure classification or a
    rollback that did not succeed caps the score well below that."""
    if learning_record.get("failure_classification"):
        return 0.1
    if learning_record.get("rollback_result") not in (None, "not_needed", "succeeded"):
        return 0.2

    def agreement(predicted, observed):
        if predicted is None or observed is None:
            return 0.5
        if predicted == 0:
            return 1.0 if observed == 0 else 0.5
        return _clamp(1.0 - abs(predicted - observed) / max(abs(predicted), 1e-9))

    utility_agreement = agreement(learning_record.get("predicted_utility"), learning_record.get("observed_utility"))
    cost_agreement = agreement(learning_record.get("predicted_cost"), learning_record.get("observed_cost"))
    latency_agreement = agreement(learning_record.get("predicted_latency"), learning_record.get("observed_latency"))

    return round(_clamp((utility_agreement + cost_agreement + latency_agreement) / 3), 4)


def record_dispatch_learning(
    artifact_id: str, artifact_sha256, decision: dict, candidate_id: str, required_capabilities: list,
    predicted_utility, observed_utility, predicted_cost, observed_cost, predicted_latency, observed_latency,
    expected_outcome: str, measured_outcome, failure_classification, rollback_result,
    evidence_sufficiency: str, promotion_decision: str,
) -> dict:
    """Builds and validates a DispatchLearningRecord, computes its
    success_score deterministically, and writes it through
    router.record_outcome.record() -- the same 4-field ledger every other
    routing decision in this repository already learns from."""
    learning_record = schema.new_dispatch_learning_record(
        artifact_id=artifact_id, artifact_sha256=artifact_sha256, decision_id=decision["id"],
        candidate_id=candidate_id, predicted_utility=predicted_utility, observed_utility=observed_utility,
        predicted_cost=predicted_cost, observed_cost=observed_cost, predicted_latency=predicted_latency,
        observed_latency=observed_latency, expected_outcome=expected_outcome, measured_outcome=measured_outcome,
        failure_classification=failure_classification, rollback_result=rollback_result,
        evidence_sufficiency=evidence_sufficiency, routing_policy_delta=None, promotion_decision=promotion_decision,
    )
    errors = schema.validate_dispatch_learning_record(learning_record)
    if errors:
        raise ValueError(f"DispatchLearningRecord failed validation: {errors}")

    success_score = compute_success_score(learning_record)
    learning_record["routing_policy_delta"] = (
        f"success_score={success_score} recorded for candidate {candidate_id} under "
        f"mission_class derived from {sorted(required_capabilities)}"
    )

    from router.mission_router import mission_class as _mission_class
    cls = _mission_class(required_capabilities)

    outcome_entry = record_outcome.record(
        capability_id=candidate_id, mission_class=cls, success_score=success_score,
        notes=json.dumps({
            "learning_record_id": learning_record["id"], "decision_id": decision["id"],
            "predicted_utility": predicted_utility, "observed_utility": observed_utility,
            "predicted_cost": predicted_cost, "observed_cost": observed_cost,
            "predicted_latency": predicted_latency, "observed_latency": observed_latency,
            "failure_classification": failure_classification, "rollback_result": rollback_result,
            "evidence_sufficiency": evidence_sufficiency, "promotion_decision": promotion_decision,
        }),
    )

    from whatsapp.src import ledger as wa_ledger
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch", "stage": "DISPATCH_LEARNING", "recorded_at": now_iso(),
        "learning_record_id": learning_record["id"], "candidate_id": candidate_id,
        "success_score": success_score, "history_evidence_id": outcome_entry.get("recorded_at"),
        "state": "RECORDED",
    })

    return learning_record
