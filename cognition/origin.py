"""FW-ODCC-1: ORIGIN -- the integrity of beginnings.

origin_brief() is a READ-ONLY projection over one admitted, completed
cognitive-cycle artifact (cognition.cycle). It records nothing, runs no
lens, starts no cycle and probes nothing. It answers, from records that
already exist:

  what started this      the cycle's initiating OBSERVATION / AUDIENCE_QUESTION
                         records -- root records only. A CLAIM, lens output or
                         any other derived input is listed separately as a
                         derived input and can never be an initiating record
  how independent        re-traced live through cognition.lineage: origins are
                         independence keys, so two records with identical
                         wording but different sources stay two origins, and
                         any number of restatements of one source stay one
  what is uncertain      lens open questions (methodology notes separated, via
                         lens v2 presentation), unsupported claims, preserved
                         contradictions, caller-declared missing information
  what it would take     required capability tags vs the capability registry,
                         as integer counts ("2/4"); reachability is always
                         NOT_PROBED and a match is never an authorization
  why it matters         ESTIMATE_RECORDED commercial signals, always reported
                         as HYPOTHESIS
  what R4 decided        the governor decision recorded in the artifact
  smallest next step     the cycle's first research candidate (NOT_EVIDENCE)

Deliberately NOT imported or called: router.mission_router (route() probes
the network and appends to router/decisions.jsonl) and capabilities.discover
(probe_all() opens sockets and runs subprocesses). The registry is passed in
as data; load_capability_registry() only reads the JSON file.
"""
from __future__ import annotations

import json
from pathlib import Path

from cognition import commerce, cxp, cycle, governor as gv, lineage, presentation

BRIEF_SCHEMA = "forgeworld.origin.brief.v1"
NOT_PROBED = "NOT_PROBED"
COMPLETED = (cycle.COMPLETED_WITH_CANDIDATES, cycle.COMPLETED_NO_CANDIDATES)
INITIATING_KINDS = cycle.SOURCE_KINDS  # OBSERVATION, AUDIENCE_QUESTION

O_UNKNOWN_ARTIFACT = "UNKNOWN_OR_ALTERED_CYCLE_ARTIFACT"
O_NOT_COMPLETED = "CYCLE_NOT_COMPLETED"
O_NOT_ADMITTED = "CYCLE_NOT_ADMITTED_BY_R4"
O_NO_INITIATING = "NO_INITIATING_OBSERVATION"
O_BAD_HYPOTHESIS = "NOT_AN_ESTIMATE_RECORD"
O_BAD_TAGS = "REQUIRED_TAGS_INVALID"
O_BAD_TEXT = "MISSING_INFORMATION_TEXT_REFUSED"


class OriginRefused(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


def load_capability_registry(path: Path) -> dict:
    """Read the capability registry as data. No probe, no ledger write."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def admitted_cycle(runner, artifact_id: str) -> dict:
    """Load a cycle artifact (tamper-checked by the runner) and require that
    R4 committed an ADMIT and the full lens set completed."""
    try:
        artifact = runner.load(artifact_id)
    except (OSError, ValueError, cycle.CycleArtifactError):
        raise OriginRefused([O_UNKNOWN_ARTIFACT]) from None
    if artifact.get("termination") not in COMPLETED:
        raise OriginRefused([f"{O_NOT_COMPLETED}:{artifact.get('termination')}"])
    decision = artifact.get("governor_decision") or {}
    if decision.get("decision") != gv.ADMIT or decision.get("committed") is not True:
        raise OriginRefused([O_NOT_ADMITTED])
    return artifact


def initiating_record_ids(exchange, artifact: dict) -> list:
    """Root OBSERVATION / AUDIENCE_QUESTION inputs of the cycle, re-checked
    against the live exchange (not trusted from the artifact)."""
    out = []
    for row in artifact["evidence_classification"]:
        meta = exchange.record_metadata(row["record_id"])
        if meta and not meta["erased"] and meta["kind"] in INITIATING_KINDS:
            out.append(row["record_id"])
    return sorted(out)


def origin_brief(exchange, runner, artifact_id: str, *, capability_registry: dict, required_tags,
                 value_hypothesis_ids=(), missing_information=()) -> dict:
    artifact = admitted_cycle(runner, artifact_id)
    problems = []
    if (not isinstance(required_tags, (list, tuple)) or not required_tags
            or not all(isinstance(t, str) and t for t in required_tags)):
        problems.append(O_BAD_TAGS)
        required_tags = []
    for text in missing_information:
        try:
            commerce._check_summary(text)
        except cxp.CXPError:
            problems.append(O_BAD_TEXT)
    hypotheses = []
    for rid in sorted(set(value_hypothesis_ids)):
        meta = exchange.record_metadata(rid) if isinstance(rid, str) else None
        if (meta is None or meta["erased"] or meta["kind"] != cxp.KIND_COMMERCIAL_SIGNAL
                or meta["commerce"]["stage"] != commerce.ESTIMATE_RECORDED):
            problems.append(f"{O_BAD_HYPOTHESIS}:{rid}")
            continue
        payload = exchange.get_record(rid).payload()
        hypotheses.append({"record_id": rid, "stage": commerce.ESTIMATE_RECORDED, "reason": payload["reason"],
                           "amount": payload["amount"], "offer_ref": payload["offer_ref"],
                           "representation": meta["representation"], "status": "HYPOTHESIS_NOT_REVENUE"})
    initiating = initiating_record_ids(exchange, artifact)
    if not initiating:
        problems.append(O_NO_INITIATING)
    if problems:
        raise OriginRefused(problems)

    lookup = exchange.record_metadata
    initiating_rows = []
    for rid in initiating:
        t = lineage.trace(lookup, rid)
        meta = lookup(rid)
        initiating_rows.append({"record_id": rid, "kind": meta["kind"], "representation": meta["representation"],
                                "provenance": meta["provenance"], "epistemic_class": t["epistemic_class"],
                                "origins": sorted({s["origin"] for s in t["sources"]}),
                                "sources": [{k: s[k] for k in ("source_type", "locator", "origin")} for s in t["sources"]]})
    derived = []
    for row in artifact["evidence_classification"]:
        if row["record_id"] not in initiating:
            derived.append({"record_id": row["record_id"], "kind": row["kind"],
                            "epistemic_class": lineage.trace(lookup, row["record_id"])["epistemic_class"],
                            "role": "DERIVED_INPUT_NOT_AN_INITIATING_OBSERVATION"})
    independence = lineage.shared_origins(lookup, initiating)

    assembly = artifact["assembly"]
    open_questions = [q for q in assembly["open_questions"] if not presentation.is_methodology_note(q)]
    methodology = [q for q in assembly["open_questions"] if presentation.is_methodology_note(q)]
    tags = sorted(set(required_tags))
    matches = []
    for cap in capability_registry.get("capabilities", ()):
        matched = sorted(set(cap.get("tags", ())) & set(tags))
        if matched:
            matches.append({"capability_id": cap["id"], "matched_tags": matched, "matched_count": len(matched),
                            "required_count": len(tags), "reachability": NOT_PROBED, "authorized": False})
    matches.sort(key=lambda m: (-m["matched_count"], m["capability_id"]))
    covered = {t for m in matches for t in m["matched_tags"]}
    decision = artifact["governor_decision"]

    return {
        "schema": BRIEF_SCHEMA, "cycle_artifact_id": artifact_id, "cycle_id": decision["cycle_id"],
        "topic": artifact["topic"],
        "governance": {"decision": decision["decision"], "reason_code": decision["reason_code"],
                       "root_cycle_id": decision["root_cycle_id"], "depth": decision["depth"],
                       "termination": artifact["termination"]},
        "initiating_records": initiating_rows,
        "derived_inputs": derived,
        "independence": {"independent_origin_count": independence["independent_origin_count"],
                         "origins": independence["origins"], "repeated_origins": independence["repeated_origins"]},
        "uncertainty": {"open_questions": open_questions, "methodology_notes": methodology,
                        "unsupported_claims": assembly["unsupported_claims"],
                        "contradictions": [{"contradiction_id": d["contradiction_id"], "question": d["question"],
                                            "status": d["status"]} for d in artifact["preserved_disagreements"]],
                        "missing_information": list(missing_information)},
        "capabilities": {"required_tags": tags, "matches": matches, "uncovered_tags": sorted(set(tags) - covered),
                         "reachability": NOT_PROBED,
                         "note": "a capability match is not an authorization to execute that capability"},
        "value_hypotheses": hypotheses,
        "smallest_next_step": artifact["research_candidates"][:1],
        "statements": {"inference_is_not_observation": True, "customer_assertion_is_not_verification": True,
                       "estimates_are_not_revenue": True, "grants_execution_authority": False},
    }
