#!/usr/bin/env python3
"""Build scenes.json for the VALIDATION-001 clip strictly from evidence files
already on disk (source_record.json, requirement.json, commitment.json,
mission.json, pipeline_log.json, trace_result.json). No values are typed in
here that don't trace to one of those files, except fixed presentational
copy that the validation brief itself specified verbatim (scene headings,
Scene 10 closing lines, Scene 9's four example limitation categories, all of
which are true of this run).
"""
import json
from pathlib import Path

VALDIR = Path(__file__).resolve().parent.parent
SRC_IMG = str(VALDIR / "source" / "lorenzo_asnaghi_linkedin_exchange.png")

source_record = json.loads((VALDIR / "source_record.json").read_text())
requirement = json.loads((VALDIR / "requirement.json").read_text())
commitment = json.loads((VALDIR / "commitment.json").read_text())
mission = json.loads((VALDIR / "mission.json").read_text())
pipeline_log = json.loads((VALDIR / "pipeline_log.json").read_text())
trace_result = json.loads((VALDIR / "trace_result.json").read_text())

sha = source_record["artifact"]["sha256"]
sha_short = f"{sha[:10]}...{sha[-8:]}"


def ms(seconds):
    return f"{seconds * 1000:.1f}ms"


step_by_name = {st["step"]: st for st in pipeline_log["steps"]}

scenes = [
    {
        "id": "question",
        "type": "title",
        "duration_s": 4.2,
        "kicker": "SCENE 1 — THE QUESTION",
        "title_lines": ["FORGEWORLD", "VALIDATION 001"],
        "subtitle": "Can conversation become accountable action?",
        "screenshot_path": SRC_IMG,
        "screenshot_crop": (0, 230, 1080, 770),
    },
    {
        "id": "source",
        "type": "source",
        "duration_s": 4.8,
        "heading": "REAL-WORLD SIGNAL",
        "subheading": "External feedback received.",
        "screenshot_path": SRC_IMG,
        "screenshot_crop": (0, 860, 1080, 1810),
        "fields": [
            ("SOURCE", "LinkedIn DM - Lorenzo Asnaghi <-> James Davis"),
            ("TIMESTAMP", "TUESDAY 6:30 AM -> TODAY 6:59 AM (relative labels as shown in-app; no absolute date visible in source)"),
            ("CHANNEL", "LinkedIn mobile messaging"),
            ("HASHED", f"sha256:{sha_short}"),
        ],
        "footnote": "Source preserved unaltered, byte-for-byte. This scene shows only what was received — no interpretation yet.",
    },
    {
        "id": "extraction",
        "type": "extraction",
        "duration_s": 4.4,
        "heading": "ForgeWorld identifies:",
        "blocks": [
            {
                "label": "REQUIREMENT",
                "classification": "INTERPRETATION",
                "text": requirement["statement"],
                "height": 300,
                "note": "verbatim source (L1): \"" + requirement["supporting_substring"] + "\"",
            },
            {
                "label": "COMMITMENT",
                "classification": "SOURCE FACT",
                "text": commitment["statement"],
                "height": 300,
                "note": "verbatim source (L2): \"" + commitment["supporting_substring"] + "\"",
            },
        ],
    },
    {
        "id": "governance",
        "type": "governance",
        "duration_s": 4.0,
        "heading": "Provenance discipline",
        "chain": ["SOURCE EVIDENCE", "PROVENANCE", "EXTRACTION", "VALIDATION MISSION"],
        "note": "SOURCE EVIDENCE and PROVENANCE are source facts — files and hashes, independently checkable. EXTRACTION is where ForgeWorld's interpretation enters the chain.",
    },
    {
        "id": "mission",
        "type": "mission",
        "duration_s": 3.6,
        "mission_id": mission["mission_id"],
        "objective": mission["objective"],
        "generated_by": mission["generated_by"],
    },
    {
        "id": "execution",
        "type": "execution",
        "duration_s": 4.4,
        "heading": "Pipeline — real run",
        "steps": [
            {"name": "CAPTURE", "verdict": step_by_name["CAPTURE"]["verdict"], "duration": ms(step_by_name["CAPTURE"]["duration_s"])},
            {"name": "EXTRACT", "verdict": step_by_name["EXTRACT"]["verdict"], "duration": ms(step_by_name["EXTRACT"]["duration_s"])},
            {"name": "STRUCTURE", "verdict": step_by_name["STRUCTURE"]["verdict"], "duration": ms(step_by_name["STRUCTURE"]["duration_s"])},
            {"name": "GOVERN", "verdict": step_by_name["GOVERN"]["verdict"], "duration": ms(step_by_name["GOVERN"]["duration_s"])},
            {"name": "ROUTE", "verdict": step_by_name["ROUTE"]["verdict"], "duration": ms(step_by_name["ROUTE"]["duration_s"])},
            {"name": "TRACK", "verdict": step_by_name["TRACK"]["verdict"], "duration": ms(step_by_name["TRACK"]["duration_s"])},
        ],
        "note": f"Total pipeline time: {ms(pipeline_log['total_duration_s'])}. ROUTE and TRACK call this repo's existing router/mission_router.py and router/record_outcome.py — not reimplemented here.",
    },
    {
        "id": "trace",
        "type": "trace",
        "duration_s": 4.8,
        "question": trace_result["trace_question"],
        "chain": ["MISSION", "COMMITMENT", "REQUIREMENT", "ORIGINAL EXCHANGE (L1)", "SOURCE FILE (sha256)"],
        "verdict": trace_result["overall_verdict"],
    },
    {
        "id": "result",
        "type": "metrics",
        "duration_s": 5.4,
        "heading": "Measured outcomes",
        "metrics": [
            {"name": "source preserved", "verdict": "PASS" if step_by_name["CAPTURE"]["hash_match"] else "FAIL"},
            {"name": "source hash verified", "verdict": "PASS" if trace_result["hops"][3]["resolved"] else "FAIL"},
            {"name": "requirement extracted", "verdict": requirement["extraction_verdict"]},
            {"name": "commitment extracted", "verdict": commitment["extraction_verdict"]},
            {"name": "mission generated", "verdict": step_by_name["STRUCTURE"]["verdict"]},
            {"name": "governance separation check", "verdict": step_by_name["GOVERN"]["verdict"]},
            {"name": "mission routed to reachable capability", "verdict": step_by_name["ROUTE"]["verdict"]},
            {"name": "outcome recorded to capability history", "verdict": step_by_name["TRACK"]["verdict"]},
            {"name": "backward provenance trace successful", "verdict": trace_result["overall_verdict"]},
            {"name": "retrieval successful", "verdict": "NOT TESTED"},
            {"name": f"processing time measured ({ms(pipeline_log['total_duration_s'])})", "verdict": "PASS"},
        ],
    },
    {
        "id": "limitations",
        "type": "limitations",
        "duration_s": 3.4,
        "heading": "What remains unproven",
        "items": [
            "Single-case demonstration: one exchange, one run.",
            "Human interpretation still involved: the requirement/commitment mapping was authored by the operator, not derived automatically.",
            "Business impact not yet established.",
            "External replication required.",
        ],
    },
    {
        "id": "conclusion",
        "type": "closing",
        "duration_s": 4.4,
        "title_lines": ["FORGEWORLD", "VALIDATION 001"],
        "statement_lines": ["Architecture is a hypothesis.", "Evidence decides what survives."],
        "chain": ["REAL SIGNAL", "GOVERNED EVIDENCE", "ACTION", "MEASUREMENT", "LEARNING"],
        "logo": "ForgeWorld",
        "tagline": "Governed Workflow Intelligence",
    },
]

out = VALDIR / "scenes.json"
out.write_text(json.dumps(scenes, indent=2) + "\n")
print(f"wrote {out} ({len(scenes)} scenes, total {sum(s['duration_s'] for s in scenes):.1f}s)")
