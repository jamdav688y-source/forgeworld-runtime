"""FW-COGNITIVE-R3-001: the bounded lens coordinator.

run(input_record_ids, topic, observed_at):
  1. Accepts 1..budget.max_inputs OBSERVATION/CLAIM records (never lens
     outputs or contradictions: lens output is never lens input). Erased
     or unknown inputs stop the run before any lens is invoked.
  2. Builds ONE deeply immutable LensBrief (statements, epistemic labels,
     R2 lineage traces, recorded contradictions) shared by every lens.
  3. For each registered lens, in fixed M1..M7 order:
       an output already recorded for (lens_id, lens_version, inputs)
           -> ALREADY_PROCESSED (the lens is not invoked again), or ERASED
              if that output was erased (it cannot be re-produced: its
              content-addressed id is tombstoned);
       invocation budget spent  -> BUDGET_EXHAUSTED;
       lens raises               -> FAILED (isolated; others continue);
       CXP refuses its output    -> REJECTED with the CXP error code;
       otherwise                 -> PRODUCED, stored as a LENS_OUTPUT record.
     The coordinator, not the lens, sets the labels: provenance
     UNVERIFIED_INTERPRETATION, verification UNVERIFIED, evidence NONE for
     hypotheses/simulations/dramatizations and otherwise the WEAKEST input
     evidence, privacy the most restrictive input's. CXP independently
     re-checks all of them.
  4. For each lens question where at least one available lens SUPPORTs and
     another OPPOSEs, records (or reuses) one R2 CONTRADICTION over exactly
     those lens outputs. Nothing is averaged, voted or dropped; UNCERTAIN
     positions are listed alongside. Questions nobody opposed are reported
     as "unopposed", explicitly not as consensus.
  5. Returns a run report plus one assembly candidate built only from what
     the store holds, so the same store state always yields the same
     assembly (and assembly_id).

Bounds: at most budget.max_lens_invocations lens calls and at most
len(cxp.LENS_QUESTIONS) contradiction writes per run; no loops over its own
output; a re-entrant call (e.g. a lens calling the coordinator) is refused.
The coordinator authorizes nothing. Candidate next actions are text for a
human to consider; nothing here executes them.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

from cognition import contradiction, cxp, lineage, lenses as lenses_module
from cognition import governor as governor_module

COORDINATOR_VERSION = "1"

PRODUCED = "PRODUCED"
ALREADY_PROCESSED = "ALREADY_PROCESSED"
FAILED = "FAILED"
REJECTED = "REJECTED"
ERASED = "ERASED"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
_AVAILABLE = (PRODUCED, ALREADY_PROCESSED)

E_RECURSION_REFUSED = "RECURSION_REFUSED"
E_BAD_INPUT = "BAD_INPUT"
E_INPUT_KIND = "INPUT_KIND_NOT_ALLOWED"
E_BUDGET = "BUDGET_EXCEEDED"

GOVERNED_PURPOSE = "lens-assembly"

ASSEMBLY_SCHEMA = "forgeworld.cognition.assembly.v1"
_INPUT_KINDS = (cxp.KIND_OBSERVATION, cxp.KIND_CLAIM, cxp.KIND_AUDIENCE_QUESTION)
_UNSUPPORTED_REPRESENTATIONS = (cxp.REP_HYPOTHESIS, cxp.REP_SIMULATION, cxp.REP_DRAMATIZATION)
_FINDING_KEYS = frozenset({"statement", "positions", "uncertainties", "unsupported_claims", "next_action", "details"})
_RESOLUTION_CONDITIONS = {
    cxp.Q_CLAIM_ESTABLISHED: ["an admissible VERIFIED result for the observed claim under a human-approved policy"],
    cxp.Q_NEEDS_EXPERIMENT: ["an operator decision on whether to authorize the proposed experiment"],
    cxp.Q_READY_FOR_EPISODE: ["operator review of the assembled brief against its evidence"],
}


class CoordinatorError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class LensBudget:
    max_inputs: int = 8
    max_lens_invocations: int = len(cxp.LENS_IDS)

    def __post_init__(self):
        for name in ("max_inputs", "max_lens_invocations"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_lens_invocations > len(cxp.LENS_IDS):
            raise ValueError(f"max_lens_invocations cannot exceed {len(cxp.LENS_IDS)} (one call per lens)")


def _weakest(values, order) -> str:
    return order[min(order.index(v) for v in values)]


def _most_restrictive(values) -> str:
    return cxp.PRIVACY_CLASSES[max(cxp.PRIVACY_CLASSES.index(v) for v in values)]


class LensCoordinator:
    def __init__(self, exchange, lenses=lenses_module.LENSES, budget: LensBudget = LensBudget(), governor=None):
        seen = set()
        for lens in lenses:
            if lens.lens_id not in cxp.LENS_IDS or lens.lens_id in seen:
                raise ValueError(f"lens_id {lens.lens_id!r} is unknown or duplicated")
            if lens.representation not in cxp.REPRESENTATIONS or lens.representation == cxp.REP_QUOTATION:
                raise ValueError(f"lens {lens.lens_id} has an invalid representation")
            seen.add(lens.lens_id)
        self.exchange = exchange
        self.lenses = tuple(sorted(lenses, key=lambda l: cxp.LENS_IDS.index(l.lens_id)))
        self.budget = budget
        self.governor = governor
        self._running = False

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def run(self, input_record_ids, topic: str, observed_at: str, parent_cycle_id: str = None,
            approval_id: str = None) -> dict:
        """With a governor (R4), no lens is invoked unless the governor
        commits an ADMIT for this exact cycle; actual usage is reported back
        to it even if the run fails part-way. parent_cycle_id and
        approval_id are only meaningful with a governor."""
        if self._running:
            raise CoordinatorError(E_RECURSION_REFUSED, "the coordinator does not invoke itself")
        self._running = True
        try:
            return self._run(input_record_ids, topic, observed_at, parent_cycle_id, approval_id)
        finally:
            self._running = False

    # -- inputs and brief -------------------------------------------------------

    def _inputs(self, input_record_ids) -> list:
        ids = sorted(set(input_record_ids))
        if not ids:
            raise CoordinatorError(E_BAD_INPUT, "at least one input record is required")
        if len(ids) > self.budget.max_inputs:
            raise CoordinatorError(E_BUDGET, f"{len(ids)} inputs exceed max_inputs={self.budget.max_inputs}")
        for rid in ids:
            meta = self.exchange.record_metadata(rid)
            if meta is None:
                raise CoordinatorError(E_BAD_INPUT, f"{rid} is not an accepted record")
            if meta["erased"]:
                raise CoordinatorError(cxp.E_ERASED, f"{rid} has been erased")
            if meta["kind"] not in _INPUT_KINDS:
                raise CoordinatorError(E_INPUT_KIND, f"{meta['kind']} records are not lens input")
        return ids

    def _build_brief(self, ids: list, topic: str) -> lenses_module.LensBrief:
        inputs, traces, contradictions = [], [], set()
        for rid in ids:
            record = self.exchange.get_record(rid)
            inputs.append({"record_id": rid, "kind": record.kind, "representation": record.representation,
                           "evidence": record.evidence, "verification": record.verification,
                           "provenance": record.provenance, "privacy": record.privacy,
                           "statement": record.payload()["statement"]})
            t = lineage.trace(self.exchange.record_metadata, rid)
            traces.append({"record_id": rid, "epistemic_class": t["epistemic_class"],
                           "observation_roots": t["observation_roots"],
                           "independent_origin_count": t["independent_origin_count"],
                           "sources": [{k: s[k] for k in ("source_type", "locator", "origin", "independence_basis")}
                                       for s in t["sources"]]})
            contradictions.update(contradiction.contradictions_for(self.exchange, rid))
        origins = {s["origin"] for t in traces for s in t["sources"]}
        facts = {
            "all_verified": all(i["verification"] == cxp.VER_VERIFIED for i in inputs),
            "independent_origin_count": len(origins),
            "source_types": sorted({s["source_type"] for t in traces for s in t["sources"]}),
            "weakest_evidence": _weakest([i["evidence"] for i in inputs], cxp.EVIDENCE_CLASSES),
        }
        content = {"topic": topic, "inputs": inputs, "lineage": traces,
                   "open_contradictions": sorted(contradictions), "facts": facts}
        return lenses_module.LensBrief(
            brief_id=cxp.digest_id("brief", content), topic=topic,
            inputs=lenses_module.freeze(inputs), lineage=lenses_module.freeze(traces),
            open_contradictions=tuple(sorted(contradictions)), facts=lenses_module.freeze(facts),
        )

    # -- run ------------------------------------------------------------------

    def _run(self, input_record_ids, topic: str, observed_at: str, parent_cycle_id=None, approval_id=None) -> dict:
        if not isinstance(topic, str) or not topic.strip() or len(topic) > 256:
            raise CoordinatorError(E_BAD_INPUT, "topic must be a non-empty string of at most 256 chars")
        ids = self._inputs(input_record_ids)
        brief = self._build_brief(ids, topic)
        input_meta = [self.exchange.record_metadata(rid) for rid in ids]

        prior = {}
        for meta in self.exchange.all_record_metadata():
            if meta["kind"] == cxp.KIND_LENS_OUTPUT and meta["derived_from"] == ids:
                key = (meta["lens_id"], meta["lens_version"])
                if key not in prior or (prior[key]["erased"] and not meta["erased"]):
                    prior[key] = meta

        decision = None
        if self.governor is None:
            if parent_cycle_id is not None or approval_id is not None:
                raise CoordinatorError(E_BAD_INPUT, "cycle lineage and approvals require a governor")
        else:
            decision = self.governor.admit(governor_module.CycleRequest(
                purpose=GOVERNED_PURPOSE, input_record_ids=tuple(ids),
                planned_lens_invocations=min(len(self.lenses), self.budget.max_lens_invocations),
                parent_cycle_id=parent_cycle_id, approval_id=approval_id))
            if decision.decision != governor_module.ADMIT:
                return {"brief_id": brief.brief_id, "governor_decision": decision.to_dict(), "lens_runs": [],
                        "invocations_used": 0, "contradictions_created": 0, "assembly": None,
                        "grants_execution_authority": False}

        runs, invocations, settled = [], 0, 0
        try:
            with self.governor.running() if decision else nullcontext():
                for lens in self.lenses:
                    run = {"lens_id": lens.lens_id, "lens_version": lens.lens_version, "record_id": None, "error": None}
                    existing = prior.get((lens.lens_id, lens.lens_version))
                    if existing is not None:
                        run.update(status=ERASED if existing["erased"] else ALREADY_PROCESSED,
                                   record_id=existing["record_id"])
                    elif invocations >= self.budget.max_lens_invocations:
                        run["status"] = BUDGET_EXHAUSTED
                    else:
                        invocations += 1
                        run.update(self._invoke(lens, brief, ids, input_meta, observed_at))
                        settled += 1
                    runs.append(run)
        finally:
            if decision is not None:
                # FAILED/REJECTED lenses, plus an invocation interrupted by an
                # exception escaping this loop, all count as failures
                failures = sum(r.get("status") in (FAILED, REJECTED) for r in runs) + (invocations - settled)
                self.governor.complete(decision.cycle_id, invocations, failures)

        disagreements, unopposed, created = self._disagreements(runs, brief, observed_at)
        assembly = self._assemble(brief, ids, runs, disagreements, unopposed)
        return {
            "brief_id": brief.brief_id,
            "governor_decision": None if decision is None else decision.to_dict(),
            "lens_runs": runs,
            "invocations_used": invocations,
            "budget": {"max_inputs": self.budget.max_inputs, "max_lens_invocations": self.budget.max_lens_invocations},
            "contradictions_created": created,
            "assembly": assembly,
            "grants_execution_authority": False,
        }

    def _invoke(self, lens, brief, ids, input_meta, observed_at) -> dict:
        try:
            finding = lens.analyze(brief)
            if not isinstance(finding, dict) or set(finding) != _FINDING_KEYS:
                raise cxp.CXPError(cxp.E_MALFORMED, f"a finding must have exactly {sorted(_FINDING_KEYS)}")
        except cxp.CXPError as exc:
            return {"status": REJECTED, "error": exc.code}
        except Exception as exc:  # noqa: BLE001 -- one lens's failure must never reach another
            return {"status": FAILED, "error": type(exc).__name__}
        evidence = (cxp.EV_NONE if lens.representation in _UNSUPPORTED_REPRESENTATIONS
                    else _weakest([m["evidence"] for m in input_meta], cxp.EVIDENCE_CLASSES))
        event = {
            "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_LENS_OUTPUT,
            "representation": lens.representation, "evidence": evidence, "verification": cxp.VER_UNVERIFIED,
            "provenance": cxp.UNVERIFIED_INTERPRETATION,
            "privacy": _most_restrictive([m["privacy"] for m in input_meta]),
            "payload": {"lens_id": lens.lens_id, "lens_version": lens.lens_version, **finding},
            "sources": [], "derived_from": list(ids), "verification_ref": None, "consent_ref": None,
            "occurrence": {"emitter_id": f"lens-{lens.lens_id.lower()}", "observed_at": observed_at,
                           "correlation_id": brief.brief_id, "causation_id": None},
        }
        receipt = self.exchange.ingest(event)
        if receipt.status == "REJECTED":
            return {"status": REJECTED, "error": receipt.error_code, "record_id": receipt.record_id}
        return {"status": PRODUCED if receipt.status == "ACCEPTED" else ALREADY_PROCESSED,
                "record_id": receipt.record_id}

    # -- disagreement ---------------------------------------------------------

    def _disagreements(self, runs, brief, observed_at) -> tuple:
        available = {r["lens_id"]: self.exchange.record_metadata(r["record_id"])
                     for r in runs if r["status"] in _AVAILABLE}
        existing = {tuple(m["contradiction_claims"]): m["record_id"] for m in self.exchange.all_record_metadata()
                    if m["kind"] == cxp.KIND_CONTRADICTION and not m["erased"]}
        disagreements, unopposed, created = [], [], 0
        for question in cxp.LENS_QUESTIONS:
            by_position = {p: sorted(lid for lid, m in available.items() if m["lens_positions"].get(question) == p)
                           for p in cxp.POSITIONS}
            support, oppose = by_position[cxp.POS_SUPPORT], by_position[cxp.POS_OPPOSE]
            if support and oppose:
                claims = sorted(available[lid]["record_id"] for lid in support + oppose)
                cid = existing.get(tuple(claims))
                if cid is None:
                    cid = self._record_contradiction(question, claims, by_position, available, brief, observed_at)
                    created += cid is not None
                status = None if cid is None else contradiction.assess(self.exchange, cid)["status"]
                disagreements.append({"question": question, "positions": by_position,
                                      "contradiction_id": cid, "contradiction_status": status})
            elif support or oppose:
                position = cxp.POS_SUPPORT if support else cxp.POS_OPPOSE
                unopposed.append({"question": question, "position": position, "lenses": support or oppose,
                                  "uncertain": by_position[cxp.POS_UNCERTAIN],
                                  "note": "no lens took the opposite position; this is not consensus and verifies nothing"})
        return disagreements, unopposed, created

    def _record_contradiction(self, question, claims, by_position, available, brief, observed_at):
        event = {
            "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_CONTRADICTION,
            "representation": cxp.REP_INFERENCE, "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
            "provenance": cxp.DERIVED,
            "privacy": _most_restrictive([m["privacy"] for m in available.values() if m["record_id"] in claims]),
            "payload": {"claims": claims, "resolution_conditions": _RESOLUTION_CONDITIONS[question],
                        "summary": (f"Lenses disagree on {question}: SUPPORT {', '.join(by_position[cxp.POS_SUPPORT])}"
                                    f" vs OPPOSE {', '.join(by_position[cxp.POS_OPPOSE])}.")},
            "sources": [], "derived_from": claims, "verification_ref": None, "consent_ref": None,
            "occurrence": {"emitter_id": "lens-coordinator", "observed_at": observed_at,
                           "correlation_id": brief.brief_id, "causation_id": None},
        }
        receipt = self.exchange.ingest(event)
        return receipt.record_id if receipt.status != "REJECTED" else None

    # -- assembly -------------------------------------------------------------

    def _assemble(self, brief, ids, runs, disagreements, unopposed) -> dict:
        lens_results, open_questions, unsupported, actions, seed = [], set(), set(), [], None
        for run in runs:
            result = {"lens_id": run["lens_id"], "lens_version": run["lens_version"], "input_record_ids": ids,
                      "available": run["status"] in _AVAILABLE, "record_id": None}
            if result["available"]:
                record = self.exchange.get_record(run["record_id"])
                payload = record.payload()
                trace = lineage.trace(self.exchange.record_metadata, record.record_id)
                result.update({
                    "record_id": record.record_id, "representation": record.representation,
                    "evidence": record.evidence, "verification": record.verification,
                    "provenance": record.provenance, "statement": payload["statement"],
                    "positions": payload["positions"], "uncertainties": payload["uncertainties"],
                    "unsupported_claims": payload["unsupported_claims"], "next_action": payload["next_action"],
                    "details": payload["details"],
                    "lineage": {"epistemic_class": trace["epistemic_class"],
                                "observation_roots": trace["observation_roots"],
                                "independent_origin_count": trace["independent_origin_count"]},
                })
                open_questions.update(payload["uncertainties"])
                unsupported.update(payload["unsupported_claims"])
                if payload["next_action"]:
                    actions.append({"lens_id": run["lens_id"], "action": payload["next_action"]})
                if run["lens_id"] == "STORYWEAVER":
                    seed = {**payload["details"], "representation": record.representation,
                            "caution": "dramatization: not evidence; every scene needs checking before production"}
            lens_results.append(result)

        content = {
            "schema": ASSEMBLY_SCHEMA,
            "coordinator_version": COORDINATOR_VERSION,
            "topic": brief.topic,
            "brief_id": brief.brief_id,
            "input_record_ids": ids,
            "inputs": [{k: i[k] for k in ("record_id", "kind", "representation", "evidence", "verification", "statement")}
                       for i in brief.inputs],
            "source_lineage": [{"record_id": t["record_id"], "epistemic_class": t["epistemic_class"],
                                "observation_roots": list(t["observation_roots"]),
                                "independent_origin_count": t["independent_origin_count"],
                                "sources": [{k: s[k] for k in ("source_type", "locator", "independence_basis")}
                                            for s in t["sources"]]}
                               for t in brief.lineage],
            "epistemic_status": {
                "input_evidence": brief.facts["weakest_evidence"],
                "input_verification": cxp.VER_VERIFIED if brief.facts["all_verified"] else cxp.VER_UNVERIFIED,
                "lens_outputs_are_evidence": False,
            },
            "complete": all(r["available"] for r in lens_results) and len(lens_results) == len(cxp.LENS_IDS),
            "lens_results": lens_results,
            "disagreements": disagreements,
            "unopposed_positions": unopposed,
            "open_questions": sorted(open_questions),
            "unsupported_claims": sorted(unsupported),
            "candidate_next_actions": actions,
            "episode_planning_seed": seed,
            "status": "CANDIDATE_REQUIRES_HUMAN_REVIEW",
            "grants_execution_authority": False,
        }
        return {"assembly_id": cxp.digest_id("assembly", content), **content}
