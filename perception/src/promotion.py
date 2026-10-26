"""HUMAN PROMOTION GATE + Knowledge Vault write.

The only path from a CapabilityProposal into canonical memory. Three
independent checks must all pass, none inferred from the others (mission:
CAPABILITY != AUTHORITY != EVIDENCE != PROMOTION):

  1. no unresolved contradiction -- checked first and cheaply, because a
     disputed claim has no business even reaching an authority/evidence
     check ("Contradictory candidates remain visible and unresolved");
  2. governance.authority.evaluate_authority(PROMOTE_KNOWLEDGE) -- reused
     directly, with a new HUMAN_ONLY policy fixture added for this
     capability (governance/policy_defaults.json's POLICY-promote-knowledge-v1)
     rather than inventing a second authority mechanism;
  3. governance.evidence.current_evidence_state() + governance.promotion.can_promote()
     -- reused directly, reading the same evidence records proposal.py
     wrote via governance.evidence.observe().

`decided_by` must always be a human identifier: schema.new_promotion_decision
hard-codes provider=None ("only a human may author this object"), and this
function additionally refuses actor_kind="agent" outright -- an autonomous
call into this function is itself a bug, not a permission this module will
quietly grant.

Knowledge Vault: `perception/ledgers/knowledge_vault.jsonl` does not exist
anywhere else in the repository (see 00_DISCOVERY_REPORT.md) -- it is new,
minimal, and written to *only* from here, on decision == "PROMOTED".
"""
from pathlib import Path

from governance import evidence as gov_evidence
from governance.authority import evaluate_authority
from governance.promotion import can_promote
from governance.types import AuthorityState
from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso

MODULE_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_VAULT = MODULE_ROOT / "ledgers" / "knowledge_vault.jsonl"

PROMOTE_KNOWLEDGE_CAPABILITY = "PROMOTE_KNOWLEDGE"
PROMOTE_KNOWLEDGE_TARGET = {"resource": "knowledge_vault", "target": "*"}


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def evaluate_promotion(
    observation: dict, proposal: dict, claims_by_id: dict, decided_by: str,
) -> dict:
    """Runs the human promotion gate for `proposal` and returns a validated
    PromotionDecision. Never writes to the Knowledge Vault itself --
    call write_to_knowledge_vault() separately once you have inspected the
    decision, so a caller can never mistake "decision computed" for
    "decision executed"."""
    if not decided_by or decided_by.strip() == "":
        raise ValueError("decided_by must identify the human making this decision")

    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]

    linked_claims = [claims_by_id[cid] for cid in proposal["evidence_references"] if cid in claims_by_id]

    contradicted = [c for c in linked_claims if c["validation_status"] == "contradicted-claim"]
    if contradicted:
        decision_obj = schema.new_promotion_decision(
            image_id=image_id, image_sha256=image_sha256, proposal_id=proposal["id"],
            decision="DEFERRED", decided_by=decided_by,
            reason=(
                f"Deferred: {len(contradicted)} linked claim(s) are contradicted-claim "
                f"(unresolved contradiction) -- promotion blocked before authority/evidence "
                f"were even checked."
            ),
            authority_decision="NOT_CHECKED", evidence_state="NOT_CHECKED",
        )
        errors = schema.validate_promotion_decision(decision_obj)
        if errors:
            raise ValueError(f"PromotionDecision failed validation: {errors}")
        _record(
            "HUMAN_PROMOTION_GATE", image_sha256=image_sha256, observation_id=observation["id"],
            proposal_id=proposal["id"], decision="DEFERRED", reason="unresolved_contradiction",
            decided_by=decided_by, state="DECIDED",
        )
        return decision_obj

    evidence_subject = f"perception:proposal:{proposal['id']}"
    evidence_state = gov_evidence.current_evidence_state(evidence_subject)

    authority_decision = evaluate_authority(
        actor_id=decided_by, capability=PROMOTE_KNOWLEDGE_CAPABILITY, target=PROMOTE_KNOWLEDGE_TARGET,
    )

    # to_state="SUPPORTED", not "VALIDATED": governance.evidence.SUPPORTED is
    # exactly "independent corroboration" (proposal.py records one OBSERVED
    # per distinct source domain) -- the true ceiling of evidence strength
    # this pipeline produces, since nothing here calls gov_evidence.validate()
    # (an explicit, separate re-verification step this proof does not claim
    # to perform). Targeting "VALIDATED" would silently require a stronger
    # evidence class than corroboration alone ever satisfies.
    governance_decision = can_promote(
        artifact_id=proposal["id"], from_state="CANDIDATE_MATCH", to_state="SUPPORTED",
        evidence_state=evidence_state, authority_decision=authority_decision,
        actor_kind="human",
    )

    if governance_decision.allowed:
        decision = "PROMOTED"
    elif authority_decision.decision in (AuthorityState.DENIED,):
        decision = "REJECTED"
    else:
        # UNKNOWN authority, insufficient evidence, or any other non-allowed
        # state: not enough to promote, but not a permanent rejection either.
        decision = "DEFERRED"

    decision_obj = schema.new_promotion_decision(
        image_id=image_id, image_sha256=image_sha256, proposal_id=proposal["id"],
        decision=decision, decided_by=decided_by, reason=governance_decision.reason,
        authority_decision=authority_decision.decision.value, evidence_state=evidence_state.value,
    )
    errors = schema.validate_promotion_decision(decision_obj)
    if errors:
        raise ValueError(f"PromotionDecision failed validation: {errors}")

    _record(
        "HUMAN_PROMOTION_GATE", image_sha256=image_sha256, observation_id=observation["id"],
        proposal_id=proposal["id"], decision=decision, evidence_state=evidence_state.value,
        authority_decision=authority_decision.decision.value, decided_by=decided_by, state="DECIDED",
    )
    return decision_obj


def write_to_knowledge_vault(proposal: dict, decision: dict) -> None:
    """Append `proposal` to the Knowledge Vault. Fails closed: refuses to
    write anything not carrying an actual decision == "PROMOTED" -- this
    is the last line of defense against a visual-similarity result (or
    any other unpromoted object) ever reaching canonical memory."""
    if decision.get("decision") != "PROMOTED":
        raise ValueError(
            f"refusing to write to Knowledge Vault: decision is {decision.get('decision')!r}, not 'PROMOTED'"
        )
    if not decision.get("evidence_references") or decision["evidence_references"][0] != proposal["id"]:
        raise ValueError("decision does not reference this proposal")

    entry = {
        "proposal": proposal,
        "promotion_decision": decision,
        "written_at": now_iso(),
    }
    wa_ledger.append(KNOWLEDGE_VAULT, entry)
    _record(
        "KNOWLEDGE_VAULT", image_sha256=proposal["source_image_sha256"],
        proposal_id=proposal["id"], promotion_decision_id=decision["id"], state="WRITTEN",
    )
