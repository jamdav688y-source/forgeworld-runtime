"""FW-LIVING-FORGE-CONVERGENCE-001: one complete, governed cognitive cycle.

This is an integration adapter, not a new subsystem. It strings together
contracts that already exist and are tested on their own:

    source event ──► CXP exchange (R1)         OBSERVE / RECORD EXPERIENCE
                 ──► lineage (R2)              CLASSIFY EVIDENCE
                 ──► R4 governor admission     REQUEST GOVERNANCE DECISION
                 ──► seven lenses (R3)         ACTIVATE LENSES / SYNTHESIZE
                 ──► contradictions (R2)       IDENTIFY CONTRADICTIONS
                 ──► research candidates       GENERATE HYPOTHESES / COMPILE EXPERIMENT
                 ──► governor completion       RECORD OUTCOME (usage)
                 ──► cycle artifact            PROPOSE NEXT CYCLE + termination reason

and writes ONE content-addressed, durable cycle artifact for every attempt,
admitted or not, so every attempt ends with an explicit termination reason.

WHAT THIS CYCLE DELIBERATELY DOES NOT DO
  - Execute any experiment. Research candidates are PROPOSED text with
    evidence status NOT_EVIDENCE; they are never ingested as records, so
    they cannot become observations, and running one needs a human.
  - Evaluate capability promotion. CapabilityPromotionGate lives in
    substrate/, which is not on this branch (decision D1); the artifact says
    so instead of pretending.
  - Claim improvement. The measurement block reports what this cycle
    counted and states that there is no comparable baseline.
  - Re-enter itself. A next cycle is only *proposed*: it must be started by
    a caller with a NEW observation, and R4 decides it like any other.

Only OBSERVATION and AUDIENCE_QUESTION events are accepted as cycle sources; commercial records
and cognitive outputs can enter a cycle only as already-accepted inputs,
where R4 applies its NEEDS_HUMAN rules.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evidence_envelope import envelope
from cognition import coordinator as co, cxp, governor as gv, lenses as lenses_module, lineage

ARTIFACT_SCHEMA = "forgeworld.cognition.cycle_artifact.v1"

COMPLETED_WITH_CANDIDATES = "COMPLETED_WITH_RESEARCH_CANDIDATES"
COMPLETED_NO_CANDIDATES = "COMPLETED_NO_RESEARCH_CANDIDATES"
COMPLETED_PARTIAL = "COMPLETED_PARTIAL_LENS_SET"
REFUSED = "REFUSED_BY_GOVERNOR"
AWAITING_HUMAN = "AWAITING_HUMAN_APPROVAL"
SOURCE_REJECTED = "SOURCE_REJECTED"

CANDIDATE_RESOLVE_CONTRADICTION = "RESOLVE_CONTRADICTION"
CANDIDATE_EXPERIMENT = "EXPERIMENT"

SOURCE_KINDS = (cxp.KIND_OBSERVATION, cxp.KIND_AUDIENCE_QUESTION)


class CycleArtifactError(Exception):
    pass


def _ancestry_origins(governor, cycle_id) -> list:
    admitted = {e["cycle_id"]: e for e in governor.ledger_entries() if e["entry"] == "ADMITTED"}
    origins, current = set(), cycle_id
    while current is not None and current in admitted:
        origins.update(admitted[current]["origins"])
        current = admitted[current]["parent_cycle_id"]
    return sorted(origins)


def _usage(governor, cycle_id):
    for e in governor.ledger_entries():
        if e["entry"] == "COMPLETED" and e["cycle_id"] == cycle_id:
            return {"lens_invocations": e["lens_invocations"], "lens_failures": e["failures"],
                    "cost_units": e["cost_units"], "cost_unit": governor.policy.cost_unit}
    return None


class CycleRunner:
    def __init__(self, exchange, governor, artifact_root: Path, lenses=lenses_module.LENSES,
                 budget: co.LensBudget = co.LensBudget()):
        if governor is None:
            raise ValueError("a cycle always runs under the R4 governor")
        self.exchange = exchange
        self.governor = governor
        self.coordinator = co.LensCoordinator(exchange, lenses, budget, governor=governor)
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    @property
    def grants_execution_authority(self) -> bool:
        return False

    # -- the cycle --------------------------------------------------------------

    def run(self, source_events, topic: str, observed_at: str, parent_cycle_id: str = None,
            approval_id: str = None, extra_input_ids=()) -> dict:
        base = {"topic": topic, "parent_cycle_id": parent_cycle_id}

        # OBSERVE / RECORD EXPERIENCE: only observation-like events are cycle sources
        input_ids, intake = list(extra_input_ids), []
        for event in source_events:
            if not isinstance(event, dict) or event.get("kind") not in SOURCE_KINDS:
                return self._persist({**base, "termination": SOURCE_REJECTED, "source_intake": intake,
                                      "detail": "cycle sources must be OBSERVATION or AUDIENCE_QUESTION events"})
            receipt = self.exchange.ingest(event)
            intake.append({"status": receipt.status, "record_id": receipt.record_id, "error_code": receipt.error_code})
            if receipt.status == "REJECTED":
                return self._persist({**base, "termination": SOURCE_REJECTED, "source_intake": intake,
                                      "detail": receipt.detail})
            input_ids.append(receipt.record_id)
        if not input_ids:
            return self._persist({**base, "termination": SOURCE_REJECTED, "source_intake": intake,
                                  "detail": "a cycle needs at least one source"})

        # CLASSIFY EVIDENCE (R2), before any lens runs
        classification = []
        for rid in sorted(set(input_ids)):
            t = lineage.trace(self.exchange.record_metadata, rid)
            meta = self.exchange.record_metadata(rid)
            classification.append({
                "record_id": rid, "kind": meta["kind"], "representation": meta["representation"],
                "evidence": meta["evidence"], "verification": meta["verification"],
                "epistemic_class": t["epistemic_class"], "observation_roots": t["observation_roots"],
                "sources": [{k: s[k] for k in ("source_type", "locator", "origin", "independence_basis")}
                            for s in t["sources"]],
                "independent_origin_count": t["independent_origin_count"]})

        # GOVERNANCE DECISION + LENSES + CONTRADICTIONS + SYNTHESIS (R4 -> R3 -> R2)
        try:
            report = self.coordinator.run(input_ids, topic, observed_at, parent_cycle_id, approval_id)
        except co.CoordinatorError as exc:
            return self._persist({**base, "termination": SOURCE_REJECTED, "source_intake": intake,
                                  "evidence_classification": classification, "detail": f"{exc.code}: {exc.detail}"})
        decision = report["governor_decision"]
        body = {**base, "source_intake": intake, "evidence_classification": classification,
                "governor_decision": decision}
        if decision["decision"] == gv.NEEDS_HUMAN:
            return self._persist({**body, "termination": AWAITING_HUMAN, "detail": decision["detail"]})
        if decision["decision"] != gv.ADMIT:
            return self._persist({**body, "termination": REFUSED, "detail": decision["reason_code"]})

        assembly = report["assembly"]
        candidates = self._research_candidates(decision["cycle_id"], assembly)
        usage = _usage(self.governor, decision["cycle_id"])
        if not assembly["complete"]:
            termination = COMPLETED_PARTIAL
        else:
            termination = COMPLETED_WITH_CANDIDATES if candidates else COMPLETED_NO_CANDIDATES
        return self._persist({
            **body,
            "termination": termination,
            "lens_runs": [{k: r[k] for k in ("lens_id", "status", "record_id", "error")} for r in report["lens_runs"]],
            "assembly": assembly,
            "preserved_disagreements": [
                {"question": d["question"], "positions": d["positions"], "contradiction_id": d["contradiction_id"],
                 "status": d["contradiction_status"]} for d in assembly["disagreements"]],
            "research_candidates": candidates,
            "experiment_execution": "NOT_PERFORMED: no experiment runs without separate human authorization",
            "capability_promotion": "NOT_EVALUATED: CapabilityPromotionGate (substrate/) is not on this branch",
            "next_cycle": {
                "parent_cycle_id": decision["cycle_id"],
                "requires": "a new OBSERVATION citing a source origin outside excluded_origins, admitted by R4",
                "excluded_origins": _ancestry_origins(self.governor, decision["cycle_id"]),
                "started_automatically": False,
            },
            "measurement": {
                "baseline": None,
                "improvement_claim": None,
                "note": "one cycle with no comparable baseline: these are counts, not improvements",
                "inputs": len(classification),
                "inputs_traced_to_observations": sum(bool(c["observation_roots"]) for c in classification),
                "independent_origins": len({s["origin"] for c in classification for s in c["sources"]}),
                "lenses_available": sum(r["available"] for r in assembly["lens_results"]),
                "contradictions_detected": len(assembly["disagreements"]),
                "unsupported_claims_flagged": len(assembly["unsupported_claims"]),
                "research_candidates": len(candidates),
                "human_corrections_required": None,
                "usage": usage,
            },
        })

    # -- research candidates ------------------------------------------------------

    def _research_candidates(self, cycle_id: str, assembly: dict) -> list:
        """Deterministic proposals drawn only from what the assembly holds:
        one per open lens disagreement, plus one experiment when the
        experiment question went unopposed. Never ingested; never evidence."""
        excluded = _ancestry_origins(self.governor, cycle_id)
        by_lens = {r["lens_id"]: r for r in assembly["lens_results"] if r["available"]}
        out = []
        for d in assembly["disagreements"]:
            record = self.exchange.get_record(d["contradiction_id"]) if d["contradiction_id"] else None
            if record is None or d["contradiction_status"] != "OPEN":
                continue
            out.append({"type": CANDIDATE_RESOLVE_CONTRADICTION, "question": d["question"],
                        "contradiction_id": d["contradiction_id"], "positions": d["positions"],
                        "resolution_conditions": record.payload()["resolution_conditions"],
                        "evidence_needed": "a new observation from an origin outside excluded_origins, "
                                           "or an admissible VERIFICATION_RESULT"})
        experiment_wanted = any(u["question"] == cxp.Q_NEEDS_EXPERIMENT and u["position"] == cxp.POS_SUPPORT
                                for u in assembly["unopposed_positions"])
        if experiment_wanted and "CATALYST" in by_lens:
            out.append({"type": CANDIDATE_EXPERIMENT,
                        "proposal": by_lens["CATALYST"]["details"].get("candidate_experiment"),
                        "falsifier": by_lens.get("SCIENTIST", {}).get("details", {}).get("falsifier"),
                        "proposed_by": next(u["lenses"] for u in assembly["unopposed_positions"]
                                            if u["question"] == cxp.Q_NEEDS_EXPERIMENT),
                        "evidence_needed": "an EXPERIMENT-type source recording the observed result"})
        candidates = []
        for c in out:
            c = {**c, "cycle_id": cycle_id, "status": "PROPOSED", "evidence_status": "NOT_EVIDENCE",
                 "excluded_origins": excluded, "requires_human_authorization": True,
                 "requires_governor_admission": True}
            candidates.append({"candidate_id": cxp.digest_id("candidate", c), **c})
        return candidates

    # -- durable, content-addressed artifact --------------------------------------------

    def _persist(self, body: dict) -> dict:
        content = {"schema": ARTIFACT_SCHEMA, **body,
                   "exchange_state_digest": self.exchange.state_digest(),
                   "governor_ledger_sha256": hashlib.sha256(
                       envelope._serialize_ledger(list(self.governor.ledger_entries()))).hexdigest(),
                   "grants_execution_authority": False}
        artifact = {"artifact_id": cxp.digest_id("cycle_artifact", content), **content}
        path = self.artifact_root / f"{artifact['artifact_id']}.json"
        data = cxp.canonical_bytes(artifact)
        if path.exists():
            if path.read_bytes() != data:
                raise CycleArtifactError(f"{path.name} exists with different content")
        else:
            envelope._atomic_write_bytes(path, data)
        return artifact

    def load(self, artifact_id: str) -> dict:
        """Read an artifact back, failing closed if it no longer matches its id."""
        artifact = json.loads((self.artifact_root / f"{artifact_id}.json").read_text(encoding="utf-8"))
        content = {k: v for k, v in artifact.items() if k != "artifact_id"}
        if artifact.get("artifact_id") != artifact_id or cxp.digest_id("cycle_artifact", content) != artifact_id:
            raise CycleArtifactError(f"{artifact_id} does not match its content")
        return artifact
