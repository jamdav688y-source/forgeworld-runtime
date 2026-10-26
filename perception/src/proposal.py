"""CAPABILITY PROPOSAL stage.

A CapabilityProposal is the model's opinion that something worth knowing
was observed -- never more than an opinion. `schema.new_capability_proposal`
already makes `validation_status` permanently "PROPOSED" (see
perception/src/schema.py's comment on that function); this module cannot
change that even if it wanted to, which is the point.

Every proposal's supporting evidence is recorded into
`governance/evidence_log.jsonl` via `governance.evidence.observe()` --
the *same* evidence gate the rest of ForgeWorld runtime uses (see
perception/governance/00_DISCOVERY_REPORT.md's Evidence gates reuse row),
not a perception-only evidence store. One `observe()` call per distinct
supporting source domain, so `governance.evidence.current_evidence_state()`
derives SUPPORTED for a proposal exactly when >=2 independent domains
corroborated the underlying claim -- the same "independent corroboration"
rule the governance layer already encodes, applied to a new kind of
subject (a perception proposal) rather than a second implementation of it.
"""
from urllib.parse import urlparse

from governance import evidence as gov_evidence
from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return url.lower()


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def propose_capability(
    observation: dict, claim: dict, relationship: dict, candidates_by_id: dict,
) -> dict:
    """Builds a CapabilityProposal grounded in `claim`, and feeds the
    independent-source evidence behind it into governance.evidence so the
    promotion gate (promotion.py) can later ask "how strong is the
    evidence for this proposal" using the same mechanism as everything
    else in this repository.
    """
    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]

    proposed_text = f"Perception Gateway observation: {claim['claim_text']}"
    rationale = (
        f"Derived from ExtractedClaim {claim['id']} (validation_status={claim['validation_status']}) "
        f"via EvidenceRelationship {relationship['id']} ({relationship['relationship_type']}); "
        f"independence_basis={relationship['independence_basis']!r}."
    )

    proposal = schema.new_capability_proposal(
        image_id=image_id, image_sha256=image_sha256,
        proposed_capability_text=proposed_text, rationale=rationale,
        claim_ids=[claim["id"]], confidence=claim["confidence"],
    )
    errors = schema.validate_capability_proposal(proposal)
    if errors:
        raise ValueError(f"CapabilityProposal failed validation: {errors}")
    assert proposal["validation_status"] == schema.PROPOSED  # models propose; never self-validate

    evidence_subject = f"perception:proposal:{proposal['id']}"
    seen_domains = set()
    for candidate_id in relationship["evidence_references"]:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            continue
        domain = _domain(candidate["url"])
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        gov_evidence.observe(
            subject=evidence_subject,
            observation=f"candidate {candidate['url']} ({relationship['relationship_type']})",
            source=domain,
        )

    _record(
        "CAPABILITY_PROPOSAL", image_sha256=image_sha256, observation_id=observation["id"],
        proposal_id=proposal["id"], claim_id=claim["id"], evidence_subject=evidence_subject,
        supporting_domains=sorted(seen_domains), state="PROPOSED",
        proposal=proposal,  # full object, so a later CLI `review`/`promote` can recover it
        # from the ledger alone -- the same store-the-full-record-in-the-ledger
        # pattern whatsapp/src/draft.py already uses for pending approvals,
        # not a second persistence mechanism.
    )
    return proposal
