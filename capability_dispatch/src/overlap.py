"""REGISTRY OVERLAP ANALYSIS: compares a verified CapabilityCandidate
against capabilities/registry.json -- the SAME file capabilities/discover.py
and router/mission_router.py already read, reused here via
capabilities.discover.load_registry() rather than re-parsed.

Overlap is judged on function tags, not names -- a small, deterministic,
auditable category->tags mapping (same posture as
whatsapp/src/classify.py's keyword lists: not a claim of semantic
understanding). Popularity, star counts, and social signals never appear
anywhere in this module; they cannot, because CapabilityCandidate carries
no such field in the first place (see ingest.py -- the source packet's
star-count notes stay in source_notes, free text, never promoted into a
structured, comparable field).

An unverified candidate is never compared against the registry at all --
classification is UNRESOLVED until identity_status == VERIFIED, matching
the mission's ordering (IDENTITY RESOLUTION happens before OVERLAP
ANALYSIS in the pipeline, not the other way round).
"""
from capabilities import discover

from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso

# Deterministic, hand-maintained category -> inferred function tags.
# Extend this table, do not special-case candidate names.
CATEGORY_FUNCTION_TAGS = {
    "cli_utility": {"scripting", "automation"},
    "scripting_utility": {"scripting", "automation", "data_processing"},
    "secret_scanning_cli": {"security_scanning", "secret_detection"},
    "automation_agent": {"automation", "shell_execution", "orchestration"},
    "unknown": set(),
}

FUNCTIONAL_DUPLICATE_THRESHOLD = 0.75  # fraction of candidate's tags already covered
PARTIAL_OVERLAP_THRESHOLD = 0.25


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def infer_function_tags(candidate: dict) -> set:
    return set(CATEGORY_FUNCTION_TAGS.get(candidate["normalized_category"], set()))


def analyze_overlap(artifact_id: str, artifact_sha256: str, candidate: dict) -> dict:
    """Returns a validated RegistryOverlap object. Never installs, probes,
    or executes anything -- reads capabilities/registry.json only."""
    if candidate["identity_status"] != "VERIFIED":
        overlap = schema.new_registry_overlap(
            artifact_id=artifact_id, artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
            matched_capability_ids=[], classification="UNRESOLVED",
            shared_functions=[], missing_functions=sorted(infer_function_tags(candidate)),
            conflicting_assumptions=[], recommended_disposition="BLOCK",
            confidence=0.0,
            basis=f"identity_status is {candidate['identity_status']!r}, not VERIFIED -- cannot compare against the registry",
        )
        errors = schema.validate_registry_overlap(overlap)
        if errors:
            raise ValueError(f"RegistryOverlap failed validation: {errors}")
        _record(
            "REGISTRY_OVERLAP", artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
            classification="UNRESOLVED", reason="identity_status != VERIFIED", state="ANALYZED",
        )
        return overlap

    candidate_tags = infer_function_tags(candidate)
    registry = discover.load_registry()

    best_match = None
    best_shared = set()
    for cap in registry:
        cap_tags = set(cap.get("tags", []))
        shared = candidate_tags & cap_tags
        if len(shared) > len(best_shared):
            best_shared = shared
            best_match = cap

    if not candidate_tags or best_match is None or not best_shared:
        classification = "UNIQUE_GAP"
        matched_ids = []
        shared_functions = []
        missing_functions = sorted(candidate_tags)
        disposition = "SANDBOX_PROBE"
        basis = "no existing registered capability shares any inferred function tag with this candidate"
    else:
        coverage = len(best_shared) / len(candidate_tags)
        matched_ids = [best_match["id"]]
        shared_functions = sorted(best_shared)
        missing_functions = sorted(candidate_tags - best_shared)
        if coverage >= FUNCTIONAL_DUPLICATE_THRESHOLD:
            classification = "FUNCTIONAL_DUPLICATE"
            disposition = "DUPLICATE"
            basis = (
                f"{coverage:.0%} of this candidate's inferred function tags are already "
                f"covered by existing capability '{best_match['id']}' ({sorted(best_shared)})"
            )
        elif coverage >= PARTIAL_OVERLAP_THRESHOLD:
            classification = "PARTIAL_OVERLAP"
            disposition = "ADAPT"
            basis = (
                f"{coverage:.0%} overlap with existing capability '{best_match['id']}' "
                f"({sorted(best_shared)}); {sorted(missing_functions)} not covered"
            )
        else:
            classification = "UNIQUE_GAP"
            disposition = "SANDBOX_PROBE"
            basis = (
                f"only marginal ({coverage:.0%}) overlap with the closest existing capability "
                f"'{best_match['id']}' -- treated as a gap, not a duplicate"
            )

    overlap = schema.new_registry_overlap(
        artifact_id=artifact_id, artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
        matched_capability_ids=matched_ids, classification=classification,
        shared_functions=shared_functions, missing_functions=missing_functions,
        conflicting_assumptions=[], recommended_disposition=disposition,
        confidence=0.7 if matched_ids else 0.5, basis=basis,
    )
    errors = schema.validate_registry_overlap(overlap)
    if errors:
        raise ValueError(f"RegistryOverlap failed validation: {errors}")

    _record(
        "REGISTRY_OVERLAP", artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
        classification=classification, matched_capability_ids=matched_ids,
        recommended_disposition=disposition, state="ANALYZED",
    )
    return overlap
