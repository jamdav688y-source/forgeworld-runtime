"""The eight required Perception Gateway objects. One new_x()/validate_x()
pair per object, each wrapping perception.src.common's shared envelope --
matching whatsapp/src/schema.py's exact pattern (new_event()/validate()) so
this module is recognizable to anyone who has read that one, not a second
validation style invented from scratch.
"""
from . import common

# --------------------------------------------------------------------
# 1. VisualObservation -- the root capture record.
# --------------------------------------------------------------------

OBSERVATION_VALIDATION_STATUSES = {"unvalidated", "hash_verified"}


def new_visual_observation(
    *, image_id: str, image_sha256: str, width: int, height: int,
    file_size_bytes: int, mime_type: str, capture_source: str,
    device_note: str = "", captured_at: str = None,
) -> dict:
    obj = common.build_envelope(
        "OBS", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="capture", validation_status="hash_verified",
        confidence=1.0,  # possessing the bytes and their hash is a certain fact, not a probabilistic one
        human_review_status="not_required",
        temporal_validity=common.new_temporal_validity(valid_from=captured_at),
    )
    obj.update({
        "width": width, "height": height, "file_size_bytes": file_size_bytes,
        "mime_type": mime_type, "capture_source": capture_source, "device_note": device_note,
    })
    return obj


def validate_visual_observation(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in OBSERVATION_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {OBSERVATION_VALIDATION_STATUSES}")
    for f in ("width", "height", "file_size_bytes", "mime_type", "capture_source"):
        if f not in obj:
            errors.append(f"missing required field: {f}")
    return errors


# --------------------------------------------------------------------
# 2. ExtractedSignal -- OCR text / visual fingerprint / entity, one record each.
# --------------------------------------------------------------------

SIGNAL_TYPES = {"ocr_text", "visual_fingerprint", "entity"}
SIGNAL_VALIDATION_STATUSES = {"unvalidated", "extracted"}


def new_extracted_signal(
    *, image_id: str, image_sha256: str, signal_type: str, value,
    extraction_method: str, provider: str, confidence: float,
    observation_id: str, prompt_version: str = None, raw_response=None,
) -> dict:
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"signal_type must be one of {SIGNAL_TYPES}")
    obj = common.build_envelope(
        "SIG", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method=extraction_method, validation_status="extracted",
        provider=provider, prompt_version=prompt_version, raw_response=raw_response,
        confidence=confidence, evidence_references=[observation_id],
    )
    obj.update({"signal_type": signal_type, "value": value})
    return obj


def validate_extracted_signal(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("signal_type") not in SIGNAL_TYPES:
        errors.append(f"signal_type must be one of {SIGNAL_TYPES}")
    if obj.get("validation_status") not in SIGNAL_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {SIGNAL_VALIDATION_STATUSES}")
    if "value" not in obj:
        errors.append("missing required field: value")
    if not obj.get("evidence_references"):
        errors.append("ExtractedSignal must reference the observation it was extracted from")
    return errors


# --------------------------------------------------------------------
# 3. CandidateSource -- a retrieved page/source. MUST start CANDIDATE_MATCH.
# --------------------------------------------------------------------

CANDIDATE_MATCH = "CANDIDATE_MATCH"  # required initial state -- acceptance test asserts this exact string
CANDIDATE_VALIDATION_STATUSES = {CANDIDATE_MATCH, "corroborated", "rejected"}


def new_candidate_source(
    *, image_id: str, image_sha256: str, provider: str, url: str, title: str,
    snippet: str, retrieval_confidence: float, query_signal_ids: list,
    raw_response=None,
) -> dict:
    obj = common.build_envelope(
        "CND", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="retrieval", validation_status=CANDIDATE_MATCH,
        provider=provider, raw_response=raw_response, confidence=retrieval_confidence,
        evidence_references=list(query_signal_ids),
        human_review_status="not_required",
    )
    obj.update({"url": url, "title": title, "snippet": snippet, "retrieved_at": common.now_iso()})
    return obj


def validate_candidate_source(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in CANDIDATE_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {CANDIDATE_VALIDATION_STATUSES}")
    for f in ("url", "title"):
        if not obj.get(f):
            errors.append(f"missing required field: {f}")
    return errors


# --------------------------------------------------------------------
# 4. EvidenceRelationship -- corroborates / contradicts / near_duplicate / unrelated.
# --------------------------------------------------------------------

RELATIONSHIP_TYPES = {"corroborates", "contradicts", "near_duplicate", "unrelated"}
RELATIONSHIP_VALIDATION_STATUSES = {"proposed", "validated", "rejected"}


def new_evidence_relationship(
    *, image_id: str, image_sha256: str, relationship_type: str,
    candidate_ids: list, independence_basis: str, confidence: float,
    provider: str = "perception.corroboration", raw_response=None,
) -> dict:
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError(f"relationship_type must be one of {RELATIONSHIP_TYPES}")
    if len(candidate_ids) < 1:
        raise ValueError("an EvidenceRelationship must reference at least one candidate")
    obj = common.build_envelope(
        "REL", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="corroboration_analysis", validation_status="proposed",
        provider=provider, raw_response=raw_response, confidence=confidence,
        evidence_references=list(candidate_ids),
    )
    obj.update({"relationship_type": relationship_type, "independence_basis": independence_basis})
    return obj


def validate_evidence_relationship(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("relationship_type") not in RELATIONSHIP_TYPES:
        errors.append(f"relationship_type must be one of {RELATIONSHIP_TYPES}")
    if obj.get("validation_status") not in RELATIONSHIP_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {RELATIONSHIP_VALIDATION_STATUSES}")
    if not obj.get("evidence_references"):
        errors.append("EvidenceRelationship must reference at least one candidate")
    if not obj.get("independence_basis"):
        errors.append("missing required field: independence_basis")
    return errors


# --------------------------------------------------------------------
# 5. ExtractedClaim -- reuses whatsapp/src/schema.py's EVIDENCE_CLASSES vocabulary
#    for claim strength, since it already fits ("unverified-claim" etc.).
# --------------------------------------------------------------------

CLAIM_VALIDATION_STATUSES = {"unverified-claim", "corroborated-claim", "contradicted-claim"}


def new_extracted_claim(
    *, image_id: str, image_sha256: str, claim_text: str, claim_subject: str,
    claim_predicate: str, relationship_ids: list, confidence: float,
    provider: str = "perception.claims", raw_response=None,
) -> dict:
    if not relationship_ids:
        raise ValueError("a claim can only be extracted from at least one EvidenceRelationship")
    obj = common.build_envelope(
        "CLM", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="claim_extraction", validation_status="unverified-claim",
        provider=provider, raw_response=raw_response, confidence=confidence,
        evidence_references=list(relationship_ids),
    )
    obj.update({"claim_text": claim_text, "claim_subject": claim_subject, "claim_predicate": claim_predicate})
    return obj


def validate_extracted_claim(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in CLAIM_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {CLAIM_VALIDATION_STATUSES}")
    if not obj.get("claim_text"):
        errors.append("missing required field: claim_text")
    if not obj.get("evidence_references"):
        errors.append("ExtractedClaim must reference at least one EvidenceRelationship")
    return errors


# --------------------------------------------------------------------
# 6. ContradictionRecord -- must stay visible and unresolved until a human acts.
# --------------------------------------------------------------------

CONTRADICTION_VALIDATION_STATUSES = {"unresolved", "resolved"}


def new_contradiction_record(
    *, image_id: str, image_sha256: str, description: str,
    conflicting_ids: list, confidence: float = 1.0,
    provider: str = "perception.corroboration",
) -> dict:
    if len(conflicting_ids) < 2:
        raise ValueError("a contradiction requires at least two conflicting references")
    obj = common.build_envelope(
        "CTR", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="contradiction_detection", validation_status="unresolved",
        provider=provider, confidence=confidence, evidence_references=list(conflicting_ids),
        contradiction_state="active", human_review_status="pending",
    )
    obj.update({"description": description})
    return obj


def validate_contradiction_record(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in CONTRADICTION_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {CONTRADICTION_VALIDATION_STATUSES}")
    if obj.get("contradiction_state") not in {"active", "resolved"}:
        errors.append("ContradictionRecord's own contradiction_state must be 'active' or 'resolved', never 'none'")
    if len(obj.get("evidence_references", [])) < 2:
        errors.append("ContradictionRecord must reference at least two conflicting items")
    if not obj.get("description"):
        errors.append("missing required field: description")
    return errors


# --------------------------------------------------------------------
# 7. CapabilityProposal -- models propose; validation_status can NEVER be
#    anything but PROPOSED here. There is no function anywhere in this
#    package that promotes a proposal's own validation_status field --
#    promotion is a distinct object (PromotionDecision, below), never a
#    mutation of the proposal itself. This is the enforcement mechanism
#    for "models may propose relationships but may not validate them."
# --------------------------------------------------------------------

PROPOSED = "PROPOSED"


def new_capability_proposal(
    *, image_id: str, image_sha256: str, proposed_capability_text: str,
    rationale: str, claim_ids: list, confidence: float,
    provider: str = "perception.proposal", raw_response=None,
) -> dict:
    if not claim_ids:
        raise ValueError("a proposal must be grounded in at least one ExtractedClaim")
    obj = common.build_envelope(
        "PRP", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="capability_proposal", validation_status=PROPOSED,
        provider=provider, raw_response=raw_response, confidence=confidence,
        evidence_references=list(claim_ids), human_review_status="pending",
    )
    obj.update({"proposed_capability_text": proposed_capability_text, "rationale": rationale})
    return obj


def validate_capability_proposal(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") != PROPOSED:
        errors.append(f"CapabilityProposal.validation_status must always be '{PROPOSED}' -- a model may not self-validate")
    if not obj.get("proposed_capability_text"):
        errors.append("missing required field: proposed_capability_text")
    if not obj.get("evidence_references"):
        errors.append("CapabilityProposal must be grounded in at least one ExtractedClaim")
    return errors


# --------------------------------------------------------------------
# 8. PromotionDecision -- the human gate. provider is always None: no
#    model or automated process may author this object.
# --------------------------------------------------------------------

PROMOTION_DECISIONS = {"PROMOTED", "REJECTED", "DEFERRED"}


def new_promotion_decision(
    *, image_id: str, image_sha256: str, proposal_id: str, decision: str,
    decided_by: str, reason: str, authority_decision: str, evidence_state: str,
) -> dict:
    if decision not in PROMOTION_DECISIONS:
        raise ValueError(f"decision must be one of {PROMOTION_DECISIONS}")
    obj = common.build_envelope(
        "PRO", source_image_id=image_id, source_image_sha256=image_sha256,
        extraction_method="human_promotion_decision", validation_status=decision,
        provider=None, prompt_version=None, raw_response_hash=None, confidence=None,
        evidence_references=[proposal_id], human_review_status="reviewed",
    )
    obj.update({
        "decision": decision, "decided_by": decided_by, "reason": reason,
        "authority_decision": authority_decision, "evidence_state": evidence_state,
    })
    return obj


def validate_promotion_decision(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("decision") not in PROMOTION_DECISIONS:
        errors.append(f"decision must be one of {PROMOTION_DECISIONS}")
    if obj.get("provider") is not None:
        errors.append("PromotionDecision.provider must be None -- only a human may author this object")
    if obj.get("human_review_status") != "reviewed":
        errors.append("PromotionDecision.human_review_status must be 'reviewed'")
    if not obj.get("decided_by"):
        errors.append("missing required field: decided_by")
    return errors


VALIDATORS = {
    "VisualObservation": validate_visual_observation,
    "ExtractedSignal": validate_extracted_signal,
    "CandidateSource": validate_candidate_source,
    "EvidenceRelationship": validate_evidence_relationship,
    "ExtractedClaim": validate_extracted_claim,
    "ContradictionRecord": validate_contradiction_record,
    "CapabilityProposal": validate_capability_proposal,
    "PromotionDecision": validate_promotion_decision,
}
