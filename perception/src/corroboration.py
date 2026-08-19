"""SOURCE CORROBORATION stage: turns a group of CandidateSource objects
(all CANDIDATE_MATCH, all retrieved for the same entity signal) into
EvidenceRelationship objects, and -- when candidates disagree -- a
ContradictionRecord that stays unresolved until a human acts on it.

Independence is the load-bearing concept here (mission: "A candidate cannot
enter canonical memory without corroborating evidence" and models "may
propose relationships but may not validate them"). Two candidates from the
same domain are not independent evidence of anything -- they may be the same
source mirrored or quoted. Independence is judged on distinct URL domains,
recorded explicitly in `independence_basis` so the reasoning is auditable,
not just the conclusion.

Contradiction detection is a small, explicit keyword heuristic (same
posture as whatsapp/src/classify.py's keyword lists) -- not a claim of
semantic understanding. Every relationship this module produces has
validation_status "proposed": nothing here ever promotes its own output,
matching the "propose, don't validate" doctrine enforced structurally in
perception/src/schema.py.
"""
from urllib.parse import urlparse

from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso
from .imaging import hamming_distance

# Two fingerprints this close or closer are treated as the same underlying
# screenshot with minor re-encoding/recompression noise -- see
# perception/src/imaging.py's dHash test fixtures for the calibration
# (a single-pixel perturbation in a 32x32 test image produced hamming
# distance 0; a genuinely different image produced 56). 8 leaves ample
# margin below "genuinely different" while still catching real duplicates.
NEAR_DUPLICATE_HAMMING_THRESHOLD = 8

CONTRADICTION_MARKERS = {
    "false", "hoax", "debunked", "denied", "not true", "incorrect", "fake", "disputed",
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return url.lower()


def _is_contradictory(candidate: dict) -> bool:
    text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}".lower()
    return any(marker in text for marker in CONTRADICTION_MARKERS)


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def assess_corroboration(observation: dict, candidates: list) -> dict:
    """Groups `candidates` by which entity signal they were retrieved for
    (a CandidateSource's evidence_references[0], set by retrieval.py to the
    querying entity signal's id), then judges independence and agreement
    within each group.

    Returns {"relationships": [...], "contradictions": [...]}.
    """
    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]

    groups = {}
    for cand in candidates:
        key = cand["evidence_references"][0] if cand.get("evidence_references") else "_unknown"
        groups.setdefault(key, []).append(cand)

    relationships = []
    contradictions = []

    for query_signal_id, group in groups.items():
        domains = {_domain(c["url"]): c for c in group}  # last-writer wins per domain, fine for a distinctness check
        candidate_ids = [c["id"] for c in group]
        agreeing = [c for c in group if not _is_contradictory(c)]
        disputing = [c for c in group if _is_contradictory(c)]

        if disputing and agreeing and len({_domain(c["url"]) for c in group}) >= 2:
            relationship_type = "contradicts"
            basis = (
                f"{len(agreeing)} source(s) assert, {len(disputing)} source(s) dispute, "
                f"across {len(domains)} distinct domains: {sorted(domains)}"
            )
        elif len(domains) >= 2:
            relationship_type = "corroborates"
            basis = f"{len(domains)} distinct, independent source domains: {sorted(domains)}"
        else:
            relationship_type = "unrelated"
            basis = f"only {len(domains)} distinct domain among {len(group)} candidate(s) -- not independent"

        relationship = schema.new_evidence_relationship(
            image_id=image_id, image_sha256=image_sha256, relationship_type=relationship_type,
            candidate_ids=candidate_ids, independence_basis=basis,
            confidence=0.8 if relationship_type != "unrelated" else 0.3,
        )
        errors = schema.validate_evidence_relationship(relationship)
        if errors:
            raise ValueError(f"EvidenceRelationship failed validation: {errors}")
        relationships.append(relationship)

        _record(
            "SOURCE_CORROBORATION", image_sha256=image_sha256, observation_id=observation["id"],
            relationship_id=relationship["id"], relationship_type=relationship_type,
            candidate_ids=candidate_ids, state="ASSESSED",
        )

        if relationship_type == "contradicts":
            contradiction = schema.new_contradiction_record(
                image_id=image_id, image_sha256=image_sha256,
                description=(
                    f"Candidates for query signal {query_signal_id} disagree: "
                    f"{[c['url'] for c in agreeing]} assert vs. {[c['url'] for c in disputing]} dispute."
                ),
                conflicting_ids=candidate_ids,
            )
            errors = schema.validate_contradiction_record(contradiction)
            if errors:
                raise ValueError(f"ContradictionRecord failed validation: {errors}")
            assert contradiction["validation_status"] == "unresolved"
            assert contradiction["contradiction_state"] == "active"
            contradictions.append(contradiction)

            _record(
                "SOURCE_CORROBORATION", image_sha256=image_sha256, observation_id=observation["id"],
                contradiction_id=contradiction["id"], state="CONTRADICTION_RECORDED",
            )

    return {"relationships": relationships, "contradictions": contradictions}


def compare_observation_fingerprints(
    observation_a: dict, fingerprint_signal_a: dict,
    observation_b: dict, fingerprint_signal_b: dict,
) -> dict:
    """Cross-observation near-duplicate check -- the acceptance test this
    exists for, verbatim: "Near-duplicate screenshots can be associated
    without being declared identical unless their hashes or validated
    fingerprints justify it."

    Two different VisualObservations (by construction: ingest.py
    content-addresses images by sha256, so two observations only exist here
    at all because their source_image_sha256 already differ -- byte-identical
    uploads are deduplicated before this function is ever reached) are
    compared on their *fingerprints*, never declared the same image, only
    related as "near_duplicate" when their dHash values are close. Returns
    None when the images are not close enough to relate at all -- this
    function never forces a relationship into existence.
    """
    if observation_a["source_image_sha256"] == observation_b["source_image_sha256"]:
        raise ValueError(
            "these are the same image (identical sha256) -- ingest.py should already have "
            "deduplicated them; comparing an observation to itself is not a near-duplicate check"
        )

    distance = hamming_distance(fingerprint_signal_a["value"], fingerprint_signal_b["value"])
    is_near_duplicate = distance <= NEAR_DUPLICATE_HAMMING_THRESHOLD

    _record(
        "SOURCE_CORROBORATION", stage_detail="cross_observation_fingerprint_comparison",
        observation_id_a=observation_a["id"], observation_id_b=observation_b["id"],
        hamming_distance=distance, is_near_duplicate=is_near_duplicate, state="COMPARED",
    )

    if not is_near_duplicate:
        return None

    basis = (
        f"distinct source_image_sha256 ({observation_a['source_image_sha256'][:12]}... vs "
        f"{observation_b['source_image_sha256'][:12]}...) -- NOT declared identical; "
        f"perceptual fingerprint hamming distance={distance} <= threshold={NEAR_DUPLICATE_HAMMING_THRESHOLD} "
        f"justifies association as near-duplicate, nothing stronger"
    )
    relationship = schema.new_evidence_relationship(
        image_id=observation_a["source_image_id"], image_sha256=observation_a["source_image_sha256"],
        relationship_type="near_duplicate",
        candidate_ids=[fingerprint_signal_a["id"], fingerprint_signal_b["id"]],
        independence_basis=basis, confidence=1.0,
        provider="perception.corroboration.fingerprint_comparison",
    )
    errors = schema.validate_evidence_relationship(relationship)
    if errors:
        raise ValueError(f"EvidenceRelationship failed validation: {errors}")

    _record(
        "SOURCE_CORROBORATION", stage_detail="cross_observation_fingerprint_comparison",
        relationship_id=relationship["id"], hamming_distance=distance, state="NEAR_DUPLICATE_RECORDED",
    )
    return relationship
