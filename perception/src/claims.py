"""CLAIM EXTRACTION + EVIDENCE CLASSIFICATION stages.

A claim is only ever extracted FROM an EvidenceRelationship, never directly
from a raw candidate (schema.new_extracted_claim requires at least one
relationship_id) -- a claim's evidentiary strength has to already exist
before the claim does. EVIDENCE CLASSIFICATION is realized as this claim's
own `validation_status`, using whatsapp/src/schema.py's existing
EVIDENCE_CLASSES vocabulary ("unverified-claim" / "corroborated-claim" /
"contradicted-claim") rather than inventing a second evidence-strength
scale:

  EvidenceRelationship.relationship_type -> ExtractedClaim.validation_status
  corroborates    -> corroborated-claim
  contradicts     -> contradicted-claim
  unrelated       -> unverified-claim
  near_duplicate  -> unverified-claim (duplication says nothing about truth)
"""
from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso

_CLASSIFICATION_BY_RELATIONSHIP = {
    "corroborates": "corroborated-claim",
    "contradicts": "contradicted-claim",
    "unrelated": "unverified-claim",
    "near_duplicate": "unverified-claim",
}


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def extract_claim(observation: dict, entity_signal: dict, relationship: dict) -> dict:
    """One ExtractedClaim per EvidenceRelationship. claim_subject is the
    entity text the retrieval query was built from (entities.py); the claim
    itself just states what the evidence relationship found -- it does not
    add any new assertion beyond what the relationship already established.
    """
    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]

    subject = (entity_signal.get("value") or {}).get("text", "unknown subject")
    classification = _CLASSIFICATION_BY_RELATIONSHIP.get(relationship["relationship_type"], "unverified-claim")

    predicate = {
        "corroborated-claim": "is corroborated by independent sources",
        "contradicted-claim": "is disputed across independent sources",
        "unverified-claim": "has only single-source or non-independent support",
    }[classification]

    claim_text = f"{subject} {predicate} ({relationship['independence_basis']})"

    claim = schema.new_extracted_claim(
        image_id=image_id, image_sha256=image_sha256, claim_text=claim_text,
        claim_subject=subject, claim_predicate=predicate,
        relationship_ids=[relationship["id"]], confidence=relationship["confidence"],
    )
    claim["validation_status"] = classification  # EVIDENCE CLASSIFICATION happens here
    errors = schema.validate_extracted_claim(claim)
    if errors:
        raise ValueError(f"ExtractedClaim failed validation: {errors}")

    _record(
        "CLAIM_EXTRACTION", image_sha256=image_sha256, observation_id=observation["id"],
        claim_id=claim["id"], relationship_id=relationship["id"],
        validation_status=classification, state="CLASSIFIED",
        claim=claim,  # full object, retrievable later the same way proposal.py stores proposals
    )
    return claim
