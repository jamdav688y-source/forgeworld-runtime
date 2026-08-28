#!/usr/bin/env python3
"""Labor-Market Capability Compiler.

Turns a job posting into an evidenced comparison against ForgeWorld's own
capability registry: which of the posting's responsibilities ForgeWorld can
already do (PROVEN / AVAILABLE_UNPROVEN), partially do, is blocked from
doing, requires a human operator for, or cannot do at all (MISSING). This is
the market-facing counterpart to capabilities/discover.py (which asks "is a
registered capability reachable right now?") and router/mission_router.py
(which asks "which reachable capability best fits this mission?"): this
module asks a third, prior question -- "what does the labor market pay
people to do, and where does that overlap with what ForgeWorld can prove?"

COMPLIANCE BOUNDARY (the reason ingest_posting() gates on source_type):
This module never scrapes LinkedIn or any other job board. LinkedIn's terms
prohibit automated scraping/extraction without written authorization, and
similar terms govern most job platforms. ingest_posting() therefore only
accepts postings whose source_type is one of ALLOWED_SOURCE_TYPES --
content a person manually pasted or uploaded, an employer's own career page
where collection is permitted, a licensed dataset, an authorized API, or a
public government dataset. Any other source_type (including anything that
looks like an automated-scrape label) is rejected before any extraction
happens. This module stores derived capability facts, not a republished
copy of the market's job-description text for any purpose beyond that
comparison.

EXTRACTION IS DETERMINISTIC, NOT INFERRED: capability claims are found by
matching a fixed, auditable phrase list (keyword_taxonomy.json) against the
posting text with word-boundary regexes -- never by asking a model to
"interpret" the posting. A phrase this compiler was never taught produces an
explicit UNMAPPED spec (visible taxonomy gap) rather than a guessed tag, and
a tag with no matching registry capability produces MISSING rather than a
fabricated capability. Nothing here invents reachability data: capability
classification reads the same registry.json, discover.py reachability
state, and history.jsonl the router already uses, so a claim can only be
called PROVEN on the strength of evidence that already exists elsewhere in
this repository.

CAPABILITY_STATES:
  PROVEN              matching capability is fully reachable and has at
                       least one recorded historical outcome for this tag.
  AVAILABLE_UNPROVEN  matching capability is fully reachable but has no
                       recorded historical outcome yet.
  CONNECTOR_REQUIRED  matching capability exists but its check type is
                       "manual" (an external platform an operator must
                       confirm access to, e.g. a SaaS connector).
  PLATFORM_BLOCKED    matching capability is registered but currently
                       unreachable because of missing credentials/network
                       access (check type "env" or "network").
  PARTIAL             matching capability is registered but currently
                       unreachable for a reason other than the above (e.g.
                       an unresolvable "command" check on this machine).
  MISSING             no registered capability declares this tag at all.
  OPERATOR_REQUIRED   the claim itself names human judgment/authorization
                       (approval, negotiation, sign-off) -- independent of
                       tooling, this is not a tag-matching question.
  UNMAPPED            the claim matched no taxonomy phrase at all; this is
                       a taxonomy gap, not a capability judgment -- it means
                       "we don't yet know what this claim would even need,"
                       which this module refuses to collapse into MISSING.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
CAPABILITIES_DIR = ROOT.parent / "capabilities"
POSTINGS_DIR = ROOT / "postings"
REPORTS_DIR = ROOT / "reports"
TAXONOMY_PATH = ROOT / "keyword_taxonomy.json"

sys.path.insert(0, str(CAPABILITIES_DIR))
import discover  # noqa: E402

HISTORY_PATH = CAPABILITIES_DIR / "history.jsonl"

# -- compliance boundary: see module docstring ------------------------------
ALLOWED_SOURCE_TYPES = (
    "manual_paste",
    "user_upload",
    "employer_career_page_permitted",
    "licensed_dataset",
    "authorized_api",
    "public_government_dataset",
)

POSTING_ID_MAX_LENGTH = 128
POSTING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# -- capability states -------------------------------------------------------
PROVEN = "PROVEN"
AVAILABLE_UNPROVEN = "AVAILABLE_UNPROVEN"
CONNECTOR_REQUIRED = "CONNECTOR_REQUIRED"
PLATFORM_BLOCKED = "PLATFORM_BLOCKED"
PARTIAL = "PARTIAL"
MISSING = "MISSING"
OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
UNMAPPED = "UNMAPPED"

_JUDGMENT_KEYWORDS = (
    "approve", "approval", "authorize", "authorization", "sign off",
    "sign-off", "final decision", "judgment", "judgement", "discretion",
    "negotiate", "negotiation",
)


class LaborMarketError(Exception):
    """Base error for the labor-market capability compiler."""


class UnsupportedSourceError(LaborMarketError):
    """source_type is not in ALLOWED_SOURCE_TYPES -- see the compliance
    boundary in the module docstring. This is the one check that must never
    be relaxed by a caller: it is what keeps this module from becoming an
    unauthorized scraper."""


class InvalidPostingIdError(LaborMarketError):
    """posting_id failed the canonical validation contract."""


class PostingConflictError(LaborMarketError):
    """posting_id already holds different content under a different hash."""


class PostingNotFoundError(LaborMarketError):
    """compile_report() was asked to compile a posting_id never ingested."""


def validate_posting_id(posting_id: Any) -> str:
    """Same conservative contract as evidence_envelope.validate_mission_id,
    reimplemented locally rather than imported: postings are a distinct,
    unrelated id-space from mission_id, and this module is not part of the
    mission-and-evidence envelope substrate. Never rewrites a hostile
    identifier -- returns it unchanged or raises."""
    if not isinstance(posting_id, str):
        raise InvalidPostingIdError(f"posting_id must be a string, got {type(posting_id).__name__}")
    if posting_id == "":
        raise InvalidPostingIdError("posting_id must not be empty")
    if posting_id != posting_id.strip():
        raise InvalidPostingIdError("posting_id must not have leading or trailing whitespace")
    if len(posting_id) > POSTING_ID_MAX_LENGTH:
        raise InvalidPostingIdError(f"posting_id must be at most {POSTING_ID_MAX_LENGTH} characters")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in posting_id):
        raise InvalidPostingIdError("posting_id must not contain control characters")
    if ".." in posting_id or "/" in posting_id or "\\" in posting_id:
        raise InvalidPostingIdError("posting_id must not contain path separators or '..'")
    if unicodedata.normalize("NFC", posting_id) != posting_id:
        raise InvalidPostingIdError("posting_id must already be in normalized (NFC) form")
    if not POSTING_ID_PATTERN.match(posting_id):
        raise InvalidPostingIdError(
            "posting_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ "
            "(ASCII letters, digits, '.', '_', '-' only)"
        )
    return posting_id


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Write-temp-then-rename so a reader never observes a partial file.
    This is a small, self-contained helper, not evidence_envelope's full
    fault-hook/crash-durability machinery: that machinery exists to protect
    an append-only ledger under concurrent writers, which postings/reports
    here are not (each is written once, keyed by its own posting_id)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _posting_path(posting_id: str) -> Path:
    return POSTINGS_DIR / f"{posting_id}.json"


def _report_path(posting_id: str) -> Path:
    return REPORTS_DIR / f"{posting_id}.json"


def load_taxonomy(path: Path = TAXONOMY_PATH) -> list:
    with open(path) as f:
        return json.load(f)["entries"]


# ---------------------------------------------------------------------------
# ingestion
# ---------------------------------------------------------------------------

def ingest_posting(
    posting_id: str,
    text: str,
    source_type: str,
    source_reference: str,
    provenance_note: str = "",
) -> dict:
    """Store a job posting's raw text plus provenance. Refuses any
    source_type outside ALLOWED_SOURCE_TYPES before touching the text at
    all -- see the compliance boundary in the module docstring. Re-ingesting
    identical content under the same posting_id is an idempotent no-op;
    ingesting different content under an already-used posting_id is refused
    (mirrors evidence_envelope's MissionConflictError: never silently
    overwrite a previously recorded posting)."""
    posting_id = validate_posting_id(posting_id)

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise UnsupportedSourceError(
            f"source_type {source_type!r} is not permitted. This compiler only accepts "
            f"manually provided or licensed sources: {ALLOWED_SOURCE_TYPES}. Automated "
            "scraping of job boards (LinkedIn included) is out of scope and against most "
            "platforms' terms of service."
        )
    if not isinstance(text, str) or not text.strip():
        raise LaborMarketError("posting text must be a non-empty string")
    if not isinstance(source_reference, str) or not source_reference.strip():
        raise LaborMarketError("source_reference must describe where this posting came from")

    content_sha256 = sha256_text(text)
    path = _posting_path(posting_id)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing["content_sha256"] == content_sha256:
            return existing  # idempotent replay
        raise PostingConflictError(
            f"posting_id {posting_id!r} already holds different content "
            f"(existing hash {existing['content_sha256']}, new hash {content_sha256}); "
            "use a different posting_id for different content"
        )

    record = {
        "posting_id": posting_id,
        "source_type": source_type,
        "source_reference": source_reference,
        "provenance_note": provenance_note,
        "content_sha256": content_sha256,
        "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raw_text": text,
    }
    _atomic_write_json(path, record)
    return record


def load_posting(posting_id: str) -> dict:
    posting_id = validate_posting_id(posting_id)
    path = _posting_path(posting_id)
    if not path.exists():
        raise PostingNotFoundError(f"no posting ingested under posting_id {posting_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# extraction: text -> capability specs (pure, deterministic)
# ---------------------------------------------------------------------------

_BULLET_PREFIX = re.compile(r"^[\s\-\*•]+|^\s*\d+[.)]\s*")


def _split_claim_lines(text: str) -> list:
    lines = []
    for raw_line in text.splitlines():
        cleaned = _BULLET_PREFIX.sub("", raw_line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _contains_judgment_keyword(lowered_line: str) -> Optional[str]:
    for keyword in _JUDGMENT_KEYWORDS:
        if re.search(r"\b" + re.escape(keyword) + r"\b", lowered_line):
            return keyword
    return None


def extract_capability_specs(text: str, taxonomy: list) -> list:
    """Pure function: posting text + taxonomy -> a list of capability-claim
    specs, each still unclassified (no registry/reachability lookup here).
    One line can yield zero, one, or several specs: an OPERATOR_REQUIRED
    candidate if it names human judgment, one capability-claim candidate per
    matched taxonomy phrase, and -- only if neither of those matched
    anything -- exactly one UNMAPPED candidate, so no line is ever silently
    dropped from the report."""
    specs = []
    for line_no, line in enumerate(_split_claim_lines(text), start=1):
        lowered = line.lower()
        matched_any = False

        judgment_keyword = _contains_judgment_keyword(lowered)
        if judgment_keyword:
            specs.append({
                "line_no": line_no,
                "claim_text": line,
                "kind": "operator_judgment",
                "tag": None,
                "label": "requires human authorization or judgment",
                "matched_phrase": judgment_keyword,
            })
            matched_any = True

        for entry in taxonomy:
            phrase = entry["phrase"]
            if re.search(r"\b" + re.escape(re.sub(r"\s+", " ", phrase)) + r"\b", lowered):
                specs.append({
                    "line_no": line_no,
                    "claim_text": line,
                    "kind": "capability_claim",
                    "tag": entry["tag"],
                    "label": entry["label"],
                    "matched_phrase": phrase,
                })
                matched_any = True

        if not matched_any:
            specs.append({
                "line_no": line_no,
                "claim_text": line,
                "kind": "unmapped",
                "tag": None,
                "label": None,
                "matched_phrase": None,
            })
    return specs


# ---------------------------------------------------------------------------
# classification: capability spec -> capability state (pure, deterministic)
# ---------------------------------------------------------------------------

def _capabilities_with_tag(tag: str, registry: list) -> list:
    return [cap for cap in registry if tag in cap.get("tags", [])]


def _has_historical_evidence(tag: str, history: list) -> bool:
    return any(tag in record["mission_class"].split("+") for record in history)


def classify_tag(tag: str, registry: list, reachability_state: dict, history: list) -> tuple:
    """Returns (state, evidence_str). Reads only real, already-produced
    evidence: registry.json's declared tags, discover.py's reachability
    confidences/check types, and history.jsonl's recorded outcomes. Never
    fabricates a state from the tag name alone."""
    matches = _capabilities_with_tag(tag, registry)
    if not matches:
        return MISSING, f"no registered capability declares tag {tag!r}"

    fully_reachable = [
        cap for cap in matches
        if reachability_state.get(cap["id"], {}).get("reachability_confidence") == 1.0
    ]
    if fully_reachable:
        ids = [cap["id"] for cap in fully_reachable]
        if _has_historical_evidence(tag, history):
            return PROVEN, f"reachable and historically evidenced: {ids}"
        return AVAILABLE_UNPROVEN, f"reachable, no recorded historical outcome yet: {ids}"

    manual_reachable = [
        cap for cap in matches
        if reachability_state.get(cap["id"], {}).get("reachability_confidence") == 0.5
    ]
    if manual_reachable:
        ids = [cap["id"] for cap in manual_reachable]
        return CONNECTOR_REQUIRED, f"capability requires operator-confirmed external platform access: {ids}"

    unreachable = [
        cap for cap in matches
        if reachability_state.get(cap["id"], {}).get("reachability_confidence", 0.0) == 0.0
    ]
    blocked = [cap for cap in unreachable if cap["check"]["type"] in ("env", "network")]
    if blocked:
        ids = [cap["id"] for cap in blocked]
        return PLATFORM_BLOCKED, f"capability exists but access is currently blocked (missing credentials/connectivity): {ids}"
    if unreachable:
        ids = [cap["id"] for cap in unreachable]
        return PARTIAL, f"capability mechanism is registered but not currently reachable here: {ids}"

    return PARTIAL, f"mixed or unclassified reachability evidence for tag {tag!r}"


def classify_spec(spec: dict, registry: list, reachability_state: dict, history: list) -> dict:
    if spec["kind"] == "operator_judgment":
        state, evidence = OPERATOR_REQUIRED, f"claim names human judgment ({spec['matched_phrase']!r})"
    elif spec["kind"] == "unmapped":
        state, evidence = UNMAPPED, "no taxonomy phrase matched this claim; taxonomy gap, not a capability judgment"
    else:
        state, evidence = classify_tag(spec["tag"], registry, reachability_state, history)
    return {**spec, "state": state, "evidence": evidence}


# ---------------------------------------------------------------------------
# report compilation (I/O wrapper around the pure functions above)
# ---------------------------------------------------------------------------

def load_history() -> list:
    if not HISTORY_PATH.exists():
        return []
    records = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compile_report(posting_id: str, taxonomy_path: Path = TAXONOMY_PATH) -> dict:
    """I/O wrapper: loads the ingested posting, the live capability registry,
    freshly probed reachability, and recorded history, then runs the pure
    extract/classify pipeline and writes the report atomically."""
    posting = load_posting(posting_id)
    taxonomy = load_taxonomy(taxonomy_path)
    registry = discover.load_registry()
    reachability_state = discover.probe_all()
    history = load_history()

    specs = extract_capability_specs(posting["raw_text"], taxonomy)
    classified = [classify_spec(spec, registry, reachability_state, history) for spec in specs]

    summary = {}
    for entry in classified:
        summary[entry["state"]] = summary.get(entry["state"], 0) + 1

    report = {
        "posting_id": posting_id,
        "source_type": posting["source_type"],
        "source_reference": posting["source_reference"],
        "content_sha256": posting["content_sha256"],
        "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "capability_specs": classified,
        "summary": summary,
    }
    _atomic_write_json(_report_path(posting_id), report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Labor-Market Capability Compiler.")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = sub.add_parser("ingest", help="Ingest a permitted-source job posting.")
    ingest_cmd.add_argument("--posting-id", required=True)
    ingest_cmd.add_argument("--file", required=True, help="Path to a text file containing the posting.")
    ingest_cmd.add_argument("--source-type", required=True, choices=ALLOWED_SOURCE_TYPES)
    ingest_cmd.add_argument("--source-reference", required=True)
    ingest_cmd.add_argument("--provenance-note", default="")

    compile_cmd = sub.add_parser("compile", help="Compile a capability report for an ingested posting.")
    compile_cmd.add_argument("--posting-id", required=True)

    args = parser.parse_args()

    if args.command == "ingest":
        text = Path(args.file).read_text(encoding="utf-8")
        record = ingest_posting(
            args.posting_id, text, args.source_type, args.source_reference, args.provenance_note
        )
        json.dump(record, sys.stdout, indent=2)
        print()
    elif args.command == "compile":
        report = compile_report(args.posting_id)
        json.dump(report, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
