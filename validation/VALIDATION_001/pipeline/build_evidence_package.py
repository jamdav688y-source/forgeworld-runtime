#!/usr/bin/env python3
"""Build the evidence package (MANIFEST, METRICS, top-level VALIDATION_001.json)
from files already on disk. Recomputes every hash fresh -- never copies a
previously-recorded hash without reverifying it against the live file.
"""
import hashlib
import json
import time
from pathlib import Path

VALDIR = Path(__file__).resolve().parent.parent
ROOT = VALDIR.parent.parent

ARTIFACTS = [
    ("source screenshot (original evidence)", "validation/VALIDATION_001/source/lorenzo_asnaghi_linkedin_exchange.png"),
    ("source transcript record", "validation/VALIDATION_001/source_record.json"),
    ("human annotation mapping", "validation/VALIDATION_001/pipeline/annotations.json"),
    ("requirement (extracted)", "validation/VALIDATION_001/requirement.json"),
    ("commitment (extracted)", "validation/VALIDATION_001/commitment.json"),
    ("mission (structured)", "validation/VALIDATION_001/mission.json"),
    ("governance check result", "validation/VALIDATION_001/governance_result.json"),
    ("route decision (router/mission_router.py output)", "validation/VALIDATION_001/route_decision.json"),
    ("track result (router/record_outcome.py output)", "validation/VALIDATION_001/track_result.json"),
    ("backward trace result", "validation/VALIDATION_001/trace_result.json"),
    ("full pipeline log", "validation/VALIDATION_001/pipeline_log.json"),
    ("video scene script", "validation/VALIDATION_001/scenes.json"),
    ("final rendered video", "validation/VALIDATION_001/VALIDATION_001.mp4"),
    ("pipeline orchestrator source", "validation/VALIDATION_001/pipeline/run_pipeline.py"),
    ("scene-builder source", "validation/VALIDATION_001/pipeline/build_scenes.py"),
    ("Evolution Clip renderer source", "evolution_clip/render.py"),
]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_manifest():
    rows = []
    for label, rel in ARTIFACTS:
        p = ROOT / rel
        rows.append({
            "label": label,
            "path": rel,
            "sha256": sha256_of(p),
            "size_bytes": p.stat().st_size,
        })

    lines = [
        "# VALIDATION-001 Manifest",
        "",
        f"Generated: {now()}",
        "",
        "SHA-256 for every artifact this validation depends on or produced. Recomputed at manifest-build time by hashing the files directly on disk -- not copied from an earlier log.",
        "",
        "| Artifact | Path | SHA-256 | Size (bytes) |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['label']} | `{r['path']}` | `{r['sha256']}` | {r['size_bytes']} |")

    lines += [
        "",
        "## How to reverify",
        "",
        "```",
        "sha256sum <path>",
        "```",
        "",
        "Compare against the value in this table. Any mismatch means the file has changed since this manifest was generated and the chain of evidence for this run no longer holds.",
        "",
        "## What this manifest does NOT prove",
        "",
        "- It does not prove the source screenshot is an authentic, unedited LinkedIn export -- only that the specific file bytes received in this session have not been altered since receipt.",
        "- It does not prove the requirement/commitment extraction was performed by an automated NLP system; that step was human-authored (see `pipeline/annotations.json` and Scene 9 / Limitations).",
    ]
    (VALDIR / "VALIDATION_001_MANIFEST.md").write_text("\n".join(lines) + "\n")
    return rows


def build_metrics():
    pipeline_log = json.loads((VALDIR / "pipeline_log.json").read_text())
    trace_result = json.loads((VALDIR / "trace_result.json").read_text())
    requirement = json.loads((VALDIR / "requirement.json").read_text())
    commitment = json.loads((VALDIR / "commitment.json").read_text())
    step_by_name = {s["step"]: s for s in pipeline_log["steps"]}

    metrics = [
        {"metric": "source preserved", "verdict": "PASS" if step_by_name["CAPTURE"]["hash_match"] else "FAIL", "evidence": "pipeline_log.json#steps[CAPTURE].hash_match"},
        {"metric": "source hash verified", "verdict": "PASS" if trace_result["hops"][3]["resolved"] else "FAIL", "evidence": "trace_result.json#hops[3]"},
        {"metric": "requirement extracted", "verdict": requirement["extraction_verdict"], "evidence": "requirement.json#extraction_verdict"},
        {"metric": "commitment extracted", "verdict": commitment["extraction_verdict"], "evidence": "commitment.json#extraction_verdict"},
        {"metric": "mission generated", "verdict": step_by_name["STRUCTURE"]["verdict"], "evidence": "pipeline_log.json#steps[STRUCTURE]"},
        {"metric": "governance separation check", "verdict": step_by_name["GOVERN"]["verdict"], "evidence": "governance_result.json"},
        {"metric": "mission routed to reachable capability", "verdict": step_by_name["ROUTE"]["verdict"], "evidence": "route_decision.json"},
        {"metric": "outcome recorded to capability history", "verdict": step_by_name["TRACK"]["verdict"], "evidence": "track_result.json"},
        {"metric": "backward provenance trace successful", "verdict": trace_result["overall_verdict"], "evidence": "trace_result.json#overall_verdict"},
        {"metric": "retrieval successful", "verdict": "NOT TESTED", "evidence": "No independent retrieval/query mechanism was built or exercised in this run."},
        {"metric": "processing time measured", "verdict": "PASS", "value_seconds": pipeline_log["total_duration_s"], "evidence": "pipeline_log.json#total_duration_s"},
    ]
    out = {
        "mission_id": "VALIDATION-001",
        "generated_at_utc": now(),
        "metrics": metrics,
        "verdict_scale": ["PASS", "PARTIAL", "FAIL", "NOT TESTED"],
        "rule": "A metric is PASS only if a mechanical check in run_pipeline.py or trace.py actually verified it against recorded evidence this run. Nothing here is asserted from memory or intent.",
    }
    (VALDIR / "VALIDATION_001_METRICS.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def build_bundle(manifest_rows, metrics):
    source_record = json.loads((VALDIR / "source_record.json").read_text())
    requirement = json.loads((VALDIR / "requirement.json").read_text())
    commitment = json.loads((VALDIR / "commitment.json").read_text())
    mission = json.loads((VALDIR / "mission.json").read_text())
    trace_result = json.loads((VALDIR / "trace_result.json").read_text())
    pipeline_log = json.loads((VALDIR / "pipeline_log.json").read_text())

    bundle = {
        "mission_id": "VALIDATION-001",
        "generated_at_utc": now(),
        "validation_question": "Can ForgeWorld convert an ordinary external exchange into a traceable, governed action without losing the connection to its originating evidence?",
        "source": {
            "artifact": source_record["artifact"],
            "channel": source_record["channel"],
        },
        "requirement": requirement,
        "commitment": commitment,
        "mission": mission,
        "backward_trace": trace_result,
        "pipeline_log": pipeline_log,
        "metrics_summary": metrics["metrics"],
        "manifest_artifact_count": len(manifest_rows),
        "deliverables": {
            "video": "validation/VALIDATION_001/VALIDATION_001.mp4",
            "metrics": "validation/VALIDATION_001/VALIDATION_001_METRICS.json",
            "manifest": "validation/VALIDATION_001/VALIDATION_001_MANIFEST.md",
            "report": "validation/VALIDATION_001/VALIDATION_001_REPORT.md",
        },
    }
    (VALDIR / "VALIDATION_001.json").write_text(json.dumps(bundle, indent=2) + "\n")


if __name__ == "__main__":
    rows = build_manifest()
    metrics = build_metrics()
    build_bundle(rows, metrics)
    print("wrote VALIDATION_001_MANIFEST.md, VALIDATION_001_METRICS.json, VALIDATION_001.json")
