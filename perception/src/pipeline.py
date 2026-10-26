"""Orchestrates the full mission pipeline:

  CAPTURE -> HASH -> OCR -> VISUAL FINGERPRINT -> ENTITY EXTRACTION ->
  CANDIDATE RETRIEVAL -> SOURCE CORROBORATION -> CLAIM EXTRACTION ->
  EVIDENCE CLASSIFICATION -> CAPABILITY PROPOSAL -> HUMAN PROMOTION GATE ->
  KNOWLEDGE VAULT

Every stage below is one function call into an already-independently-tested
module (ingest/ocr/entities/retrieval/corroboration/claims/proposal/promotion);
this file adds no new object types, no new validation, and no new ledger --
it only sequences calls, matching whatsapp/src/pipeline.py's own role
("orchestrates the per-event chain... kept separate... never runs inside
the webhook request/response path") for this system.

decided_by is optional and, when omitted, the pipeline stops after
CAPABILITY PROPOSAL: proposals are left PROPOSED, nothing is promoted, and
the result's `promotion_decisions` list is empty. This is the honest
default, not a shortcut -- "models may propose relationships but may not
validate them" means an unattended pipeline run must never reach a
promotion decision on its own.
"""
from . import claims as claims_mod
from . import corroboration as corroboration_mod
from . import entities as entities_mod
from . import ingest as ingest_mod
from . import ocr as ocr_mod
from . import promotion as promotion_mod
from . import proposal as proposal_mod
from . import retrieval as retrieval_mod


def run_pipeline(
    source_path, capture_source: str, ocr_provider, retrieval_provider,
    device_note: str = "", decided_by: str = None,
) -> dict:
    observation = ingest_mod.ingest_image(source_path, capture_source, device_note)
    image_bytes = ingest_mod.stored_image_path(observation["source_image_sha256"]).read_bytes()

    ocr_signal = ocr_mod.extract_ocr_signal(observation, image_bytes, ocr_provider)
    fingerprint_signal = ocr_mod.extract_fingerprint_signal(observation, image_bytes)
    entity_signals = entities_mod.extract_entities(observation, ocr_signal)
    signal_by_id = {s["id"]: s for s in entity_signals}

    candidates = []
    for entity_signal in entity_signals:
        candidates.extend(retrieval_mod.retrieve_candidates(observation, [entity_signal], retrieval_provider))
    candidates_by_id = {c["id"]: c for c in candidates}

    corroboration_result = corroboration_mod.assess_corroboration(observation, candidates)
    relationships = corroboration_result["relationships"]
    contradictions = corroboration_result["contradictions"]

    claims = []
    for relationship in relationships:
        anchor_candidate = next((c for c in candidates if c["id"] in relationship["evidence_references"]), None)
        if anchor_candidate is None or not anchor_candidate.get("evidence_references"):
            continue
        entity_signal = signal_by_id.get(anchor_candidate["evidence_references"][0])
        if entity_signal is None:
            continue
        claims.append(claims_mod.extract_claim(observation, entity_signal, relationship))
    claims_by_id = {c["id"]: c for c in claims}

    proposals = []
    for relationship in relationships:
        for claim in claims:
            if relationship["id"] not in claim["evidence_references"]:
                continue
            proposals.append(proposal_mod.propose_capability(observation, claim, relationship, candidates_by_id))

    promotion_decisions = []
    if decided_by:
        for prop in proposals:
            decision = promotion_mod.evaluate_promotion(observation, prop, claims_by_id, decided_by)
            promotion_decisions.append(decision)
            if decision["decision"] == "PROMOTED":
                promotion_mod.write_to_knowledge_vault(prop, decision)

    return {
        # OBSERVATION: what was actually captured and measured.
        "observation": observation,
        "signals": {
            "ocr": ocr_signal,
            "fingerprint": fingerprint_signal,
            "entities": entity_signals,
        },
        # INFERENCE: candidates a provider proposed, unvalidated.
        "candidates": candidates,
        # VALIDATION: independence-checked relationships, unresolved
        # contradictions, and the claims/evidence-classification derived
        # from them.
        "relationships": relationships,
        "contradictions": contradictions,
        "claims": claims,
        # PROMOTION: proposals (always PROPOSED-only) and, only when a
        # human decided_by was supplied, the resulting decisions.
        "proposals": proposals,
        "promotion_decisions": promotion_decisions,
    }
