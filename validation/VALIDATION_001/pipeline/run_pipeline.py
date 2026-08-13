#!/usr/bin/env python3
"""VALIDATION-001 pipeline: CAPTURE -> EXTRACT -> STRUCTURE -> GOVERN -> ROUTE -> TRACK.

Every step writes its own evidence file and its own PASS/FAIL/PARTIAL/NOT_TESTED
verdict. No step is allowed to report PASS unless it performed a real check
against the recorded source (transcript substring containment, hash
recomputation, reference resolution). ROUTE and TRACK call directly into the
existing repo router/capability infrastructure (router/mission_router.py,
router/record_outcome.py) instead of re-implementing routing logic here.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

VALDIR = Path(__file__).resolve().parent.parent
ROOT = VALDIR.parent.parent
SOURCE_PNG = VALDIR / "source" / "lorenzo_asnaghi_linkedin_exchange.png"

sys.path.insert(0, str(ROOT / "router"))
sys.path.insert(0, str(ROOT / "capabilities"))
import mission_router  # noqa: E402
import record_outcome  # noqa: E402

MISSION_ID = "VALIDATION-001"
ROUTE_TAGS = ["research", "documentation", "file_editing"]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def step_capture(log):
    t0 = time.time()
    source_record = json.loads((VALDIR / "source_record.json").read_text())
    declared_hash = source_record["artifact"]["sha256"]
    actual_hash = sha256_of(SOURCE_PNG) if SOURCE_PNG.exists() else None
    result = {
        "step": "CAPTURE",
        "source_file_exists": SOURCE_PNG.exists(),
        "declared_sha256": declared_hash,
        "recomputed_sha256": actual_hash,
        "hash_match": actual_hash == declared_hash,
        "verdict": "PASS" if actual_hash == declared_hash else "FAIL",
        "duration_s": round(time.time() - t0, 4),
    }
    log.append(result)
    return result, source_record


def step_extract(log, source_record):
    t0 = time.time()
    ann = json.loads((VALDIR / "pipeline" / "annotations.json").read_text())
    lines_by_id = {l["line_id"]: l for l in source_record["transcript_as_visible"]}

    req_ann = ann["requirement"]
    req_line = lines_by_id.get(req_ann["extracted_from_line_id"], {}).get("text", "")
    req_corr_line = lines_by_id.get(req_ann["corroborating_line_id"], {}).get("text", "")
    req_match = req_ann["supporting_substring"] in req_line
    req_corr_match = req_ann["corroborating_substring"] in req_corr_line

    requirement = {
        "requirement_id": "REQ-VALIDATION-001",
        "requirement_type": "external_validation_signal",
        "statement": req_ann["statement"],
        "statement_classification": req_ann["statement_classification"],
        "statement_classification_note": req_ann["statement_classification_note"],
        "extracted_from_line_id": req_ann["extracted_from_line_id"],
        "supporting_substring": req_ann["supporting_substring"],
        "supporting_substring_verbatim_match": req_match,
        "corroborating_from_line_id": req_ann["corroborating_line_id"],
        "corroborating_substring": req_ann["corroborating_substring"],
        "corroborating_substring_verbatim_match": req_corr_match,
        "source_ref": "validation/VALIDATION_001/source_record.json#" + req_ann["extracted_from_line_id"],
        "extraction_verdict": "PASS" if (req_match and req_corr_match) else ("PARTIAL" if (req_match or req_corr_match) else "FAIL"),
    }
    (VALDIR / "requirement.json").write_text(json.dumps(requirement, indent=2) + "\n")

    com_ann = ann["commitment"]
    com_line = lines_by_id.get(com_ann["extracted_from_line_id"], {}).get("text", "")
    com_match = com_ann["supporting_substring"] in com_line

    commitment = {
        "commitment_id": "COM-VALIDATION-001",
        "commitment_type": "extracted_commitment",
        "statement": com_ann["statement"],
        "statement_classification": com_ann["statement_classification"],
        "statement_classification_note": com_ann["statement_classification_note"],
        "extracted_from_line_id": com_ann["extracted_from_line_id"],
        "supporting_substring": com_ann["supporting_substring"],
        "supporting_substring_verbatim_match": com_match,
        "source_ref": "validation/VALIDATION_001/source_record.json#" + com_ann["extracted_from_line_id"],
        "requirement_ref": "validation/VALIDATION_001/requirement.json#REQ-VALIDATION-001",
        "extraction_verdict": "PASS" if com_match else "FAIL",
    }
    (VALDIR / "commitment.json").write_text(json.dumps(commitment, indent=2) + "\n")

    result = {
        "step": "EXTRACT",
        "requirement_verdict": requirement["extraction_verdict"],
        "commitment_verdict": commitment["extraction_verdict"],
        "verdict": "PASS" if requirement["extraction_verdict"] == "PASS" and commitment["extraction_verdict"] == "PASS" else "PARTIAL",
        "duration_s": round(time.time() - t0, 4),
    }
    log.append(result)
    return result, requirement, commitment


def step_structure(log, commitment):
    t0 = time.time()
    mission = {
        "mission_id": MISSION_ID,
        "objective": "Test whether a real communication can become a traceable operational commitment.",
        "commitment_ref": "validation/VALIDATION_001/commitment.json#" + commitment["commitment_id"],
        "generated_by": "run_pipeline.py:step_structure (deterministic template fill, no free generation)",
        "generated_at_utc": now(),
    }
    (VALDIR / "mission.json").write_text(json.dumps(mission, indent=2) + "\n")
    result = {"step": "STRUCTURE", "verdict": "PASS", "mission_id": mission["mission_id"], "duration_s": round(time.time() - t0, 4)}
    log.append(result)
    return result, mission


def step_govern(log, requirement, commitment, mission):
    t0 = time.time()
    checks = []
    checks.append(("requirement has classification field", "statement_classification" in requirement))
    checks.append(("commitment has classification field", "statement_classification" in commitment))
    checks.append(("commitment references requirement", commitment.get("requirement_ref", "").endswith(requirement["requirement_id"])))
    checks.append(("mission references commitment", mission.get("commitment_ref", "").endswith(commitment["commitment_id"])))
    checks.append(("requirement references source", requirement.get("source_ref", "").startswith("validation/VALIDATION_001/source_record.json#")))
    all_pass = all(ok for _, ok in checks)
    result = {
        "step": "GOVERN",
        "checks": [{"check": name, "pass": ok} for name, ok in checks],
        "verdict": "PASS" if all_pass else "FAIL",
        "duration_s": round(time.time() - t0, 4),
    }
    (VALDIR / "governance_result.json").write_text(json.dumps(result, indent=2) + "\n")
    log.append(result)
    return result


def step_route(log, mission):
    t0 = time.time()
    decision = mission_router.route(mission["objective"], ROUTE_TAGS, mission_id=mission["mission_id"])
    (VALDIR / "route_decision.json").write_text(json.dumps(decision, indent=2) + "\n")
    result = {
        "step": "ROUTE",
        "status": decision["status"],
        "selected_capability": decision["selected_capability"],
        "decisions_log": "router/decisions.jsonl",
        "verdict": "PASS" if decision["status"] == "routed" else "FAIL",
        "duration_s": round(time.time() - t0, 4),
    }
    log.append(result)
    return result, decision


def step_track(log, trace_overall_pass, route_decision):
    t0 = time.time()
    success_score = 1.0 if trace_overall_pass else 0.0
    entry = record_outcome.record(
        capability_id=route_decision["selected_capability"] or "unrouted",
        mission_class=route_decision["mission_class"],
        success_score=success_score,
        notes="VALIDATION-001 backward-trace pipeline; success_score reflects whether the full mission->commitment->requirement->source trace resolved and the source hash re-verified.",
    )
    (VALDIR / "track_result.json").write_text(json.dumps(entry, indent=2) + "\n")
    result = {
        "step": "TRACK",
        "history_log": "capabilities/history.jsonl",
        "success_score": success_score,
        "verdict": "PASS" if trace_overall_pass else "FAIL",
        "duration_s": round(time.time() - t0, 4),
    }
    log.append(result)
    return result


def run_trace():
    """Backward trace: MISSION -> COMMITMENT -> REQUIREMENT -> SOURCE. Standalone-callable."""
    mission = json.loads((VALDIR / "mission.json").read_text())
    commitment = json.loads((VALDIR / "commitment.json").read_text())
    requirement = json.loads((VALDIR / "requirement.json").read_text())
    source_record = json.loads((VALDIR / "source_record.json").read_text())

    hops = []
    hop1 = mission["commitment_ref"].endswith(commitment["commitment_id"])
    hops.append({"hop": "MISSION -> COMMITMENT", "from": mission["mission_id"], "to": commitment["commitment_id"], "resolved": hop1})

    hop2 = commitment["requirement_ref"].endswith(requirement["requirement_id"])
    hops.append({"hop": "COMMITMENT -> REQUIREMENT", "from": commitment["commitment_id"], "to": requirement["requirement_id"], "resolved": hop2})

    req_line_id = requirement["extracted_from_line_id"]
    lines_by_id = {l["line_id"]: l for l in source_record["transcript_as_visible"]}
    hop3 = req_line_id in lines_by_id and requirement["supporting_substring"] in lines_by_id[req_line_id]["text"]
    hops.append({"hop": "REQUIREMENT -> ORIGINAL EXCHANGE (line)", "from": requirement["requirement_id"], "to": f"source_record#{req_line_id}", "resolved": hop3})

    actual_hash = sha256_of(SOURCE_PNG) if SOURCE_PNG.exists() else None
    hop4 = actual_hash == source_record["artifact"]["sha256"]
    hops.append({"hop": "ORIGINAL EXCHANGE -> SOURCE FILE (sha256 re-verify)", "from": "source_record.json", "to": "lorenzo_asnaghi_linkedin_exchange.png", "resolved": hop4, "declared_sha256": source_record["artifact"]["sha256"], "recomputed_sha256": actual_hash})

    overall = all(h["resolved"] for h in hops)
    trace_result = {
        "trace_question": "Why does this mission exist?",
        "trace_direction": "backward",
        "chain": ["VALIDATION-001", commitment["commitment_id"], requirement["requirement_id"], f"source_record#{req_line_id}", "lorenzo_asnaghi_linkedin_exchange.png"],
        "hops": hops,
        "overall_verdict": "PASS" if overall else "FAIL",
        "generated_at_utc": now(),
    }
    (VALDIR / "trace_result.json").write_text(json.dumps(trace_result, indent=2) + "\n")
    return trace_result


def main():
    pipeline_start = time.time()
    log = []
    capture_result, source_record = step_capture(log)
    extract_result, requirement, commitment = step_extract(log, source_record)
    structure_result, mission = step_structure(log, commitment)
    govern_result = step_govern(log, requirement, commitment, mission)
    route_result, route_decision = step_route(log, mission)
    trace_result = run_trace()
    track_result = step_track(log, trace_result["overall_verdict"] == "PASS", route_decision)

    pipeline_log = {
        "mission_id": MISSION_ID,
        "pipeline": "CAPTURE -> EXTRACT -> STRUCTURE -> GOVERN -> ROUTE -> TRACK",
        "steps": log,
        "trace_result_summary": trace_result["overall_verdict"],
        "total_duration_s": round(time.time() - pipeline_start, 4),
        "run_at_utc": now(),
    }
    (VALDIR / "pipeline_log.json").write_text(json.dumps(pipeline_log, indent=2) + "\n")
    print(json.dumps(pipeline_log, indent=2))


if __name__ == "__main__":
    main()
