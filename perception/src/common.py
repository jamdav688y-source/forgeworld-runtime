"""Shared envelope helpers for every Perception Gateway object.

Every one of the eight required objects (VisualObservation, ExtractedSignal,
CandidateSource, EvidenceRelationship, ExtractedClaim, ContradictionRecord,
CapabilityProposal, PromotionDecision) carries the same minimum-fields
envelope the mission specifies. This module defines that envelope once,
following the exact pattern `whatsapp/src/schema.py` already established
(hand-rolled validation, no `jsonschema` dependency — none is available and
the repo has no dependency-management story) rather than inventing a second
validation style.
"""
import re
import time
import uuid

SCHEMA_VERSION = "1.0"

HEX64 = re.compile(r"^[a-f0-9]{64}$")

HUMAN_REVIEW_STATUSES = {"not_required", "pending", "reviewed"}
CONTRADICTION_STATES = {"none", "active", "resolved"}

# Shared minimum-required-fields envelope, per the mission brief verbatim:
# stable ID, schema version, creation timestamp, source image ID, source
# image SHA-256, extraction method, provider/model, prompt version,
# raw-response hash, confidence, evidence references, validation status,
# human-review status, contradiction state, temporal validity.
ENVELOPE_FIELDS = [
    "id", "schema_version", "created_at", "source_image_id", "source_image_sha256",
    "extraction_method", "provider", "prompt_version", "raw_response_hash",
    "confidence", "evidence_references", "validation_status", "human_review_status",
    "contradiction_state", "temporal_validity",
]


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def hash_raw_response(raw) -> str:
    """Hash whatever a provider actually returned, so 'we called a provider
    and got a specific, fixed response' is independently checkable later --
    never store the raw response unhashed-only or unhashed at all."""
    import json
    if isinstance(raw, (bytes, bytearray)):
        payload = bytes(raw)
    elif isinstance(raw, str):
        payload = raw.encode("utf-8")
    else:
        payload = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
    return sha256_hex(payload)


def new_temporal_validity(valid_from: str = None, valid_until: str = None) -> dict:
    return {"valid_from": valid_from or now_iso(), "valid_until": valid_until}


def build_envelope(
    id_prefix: str,
    source_image_id: str,
    source_image_sha256: str,
    extraction_method: str,
    validation_status: str,
    *,
    provider: str = None,
    prompt_version: str = None,
    raw_response=None,
    raw_response_hash: str = None,
    confidence: float = None,
    evidence_references: list = None,
    human_review_status: str = "not_required",
    contradiction_state: str = "none",
    temporal_validity: dict = None,
    id_override: str = None,
) -> dict:
    """Construct the shared envelope fields common to every object type.
    Callers add their own type-specific fields on top of this dict.
    """
    if raw_response is not None and raw_response_hash is not None:
        raise ValueError("pass raw_response OR raw_response_hash, not both")
    if raw_response is not None:
        raw_response_hash = hash_raw_response(raw_response)

    return {
        "id": id_override or new_id(id_prefix),
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "source_image_id": source_image_id,
        "source_image_sha256": source_image_sha256,
        "extraction_method": extraction_method,
        "provider": provider,
        "prompt_version": prompt_version,
        "raw_response_hash": raw_response_hash,
        "confidence": confidence,
        "evidence_references": evidence_references or [],
        "validation_status": validation_status,
        "human_review_status": human_review_status,
        "contradiction_state": contradiction_state,
        "temporal_validity": temporal_validity or new_temporal_validity(),
    }


def validate_envelope(obj: dict) -> list:
    errors = []
    for field in ENVELOPE_FIELDS:
        if field not in obj:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if obj["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be '{SCHEMA_VERSION}'")
    if obj["source_image_sha256"] is not None and not HEX64.match(obj["source_image_sha256"]):
        errors.append("source_image_sha256 must be a 64-char lowercase hex sha256 digest")
    if obj["raw_response_hash"] is not None and not HEX64.match(obj["raw_response_hash"]):
        errors.append("raw_response_hash must be a 64-char lowercase hex sha256 digest, or None")
    if obj["confidence"] is not None and not (0.0 <= obj["confidence"] <= 1.0):
        errors.append("confidence must be between 0.0 and 1.0, or None")
    if not isinstance(obj["evidence_references"], list):
        errors.append("evidence_references must be a list")
    if obj["human_review_status"] not in HUMAN_REVIEW_STATUSES:
        errors.append(f"human_review_status must be one of {HUMAN_REVIEW_STATUSES}")
    if obj["contradiction_state"] not in CONTRADICTION_STATES:
        errors.append(f"contradiction_state must be one of {CONTRADICTION_STATES}")
    tv = obj["temporal_validity"]
    if not isinstance(tv, dict) or "valid_from" not in tv or "valid_until" not in tv:
        errors.append("temporal_validity must be an object with valid_from and valid_until")

    return errors
