"""FW-CAP-DISPATCH-004 objects: one new_x()/validate_x() pair per object,
each wrapping capability_dispatch.src.common's shared envelope -- the same
pattern perception/src/schema.py and whatsapp/src/schema.py already
established, applied to a new domain rather than invented fresh.

Every CapabilityCandidate starts life at exactly the epistemic floor the
mission specifies (mission brief, verbatim):

    IDENTITY: UNVERIFIED       SAFETY: NOT_ASSESSED
    LICENSE: NOT_ASSESSED      MAINTAINABILITY: NOT_ASSESSED
    INSTALLATION: NOT_INSTALLED  AUTHORITY: NOT_GRANTED
    PROMOTION: NOT_ELIGIBLE

No function in this module can construct a CapabilityCandidate at any
stronger state -- exactly like perception/src/schema.py's
CapabilityProposal.validation_status, which can never be anything but
PROPOSED. Strengthening only happens through the identity/overlap/dispatch
modules explicitly, one step at a time, each producing its own evidenced
object rather than mutating the candidate's epistemic fields directly.
"""
from . import common

# --------------------------------------------------------------------
# Shared epistemic-state vocabularies
# --------------------------------------------------------------------

IDENTITY_STATES = {"UNVERIFIED", "VERIFIED", "AMBIGUOUS", "UNAVAILABLE", "REJECTED"}
ASSESSMENT_STATES = {"NOT_ASSESSED", "PASSED", "FAILED", "INCONCLUSIVE"}
INSTALLATION_STATES = {"NOT_INSTALLED", "SANDBOXED", "INSTALLED"}
AUTHORITY_STATES = {"NOT_GRANTED", "GRANTED_BOUNDED", "GRANTED"}
PROMOTION_STATES = {"NOT_ELIGIBLE", "ELIGIBLE_PENDING_REVIEW", "PROMOTED", "REJECTED"}
OVERLAP_STATES = {"UNIQUE_GAP", "PARTIAL_OVERLAP", "FUNCTIONAL_DUPLICATE", "ARCHITECTURAL_CONFLICT", "UNRESOLVED"}
DISPOSITIONS = {"REUSE", "ADAPT", "SANDBOX_PROBE", "OBSERVE", "DUPLICATE", "REJECT", "BLOCK"}

HARD_BLOCK_REASONS = {
    "MISSING_PROBLEM_STATEMENT", "MISSING_DESIRED_OUTCOME", "MISSING_SUCCESS_METRIC",
    "IDENTITY_AMBIGUOUS_FOR_INSTALL", "AUTHORITY_NOT_GRANTED", "LICENSE_INCOMPATIBLE",
    "UNBOUNDED_EXECUTION_SURFACE", "SECURITY_REVIEW_FAILED", "ARCHITECTURAL_CONFLICT",
    "INSUFFICIENT_EVIDENCE",
}

# --------------------------------------------------------------------
# 1. SourceObservation -- the ingested candidate-list packet itself.
# --------------------------------------------------------------------

SOURCE_OBSERVATION_VALIDATION_STATUSES = {"unvalidated", "hash_verified"}


def new_source_observation(
    *, artifact_id: str, artifact_sha256: str, media_type: str, filename: str,
    file_size_bytes: int, candidate_count: int, capture_source: str, source_notes: str = "",
) -> dict:
    obj = common.build_envelope(
        "SRC", artifact_id, artifact_sha256, extraction_method="governed_ingest",
        validation_status="hash_verified", confidence=1.0, human_review_status="not_required",
    )
    obj.update({
        "media_type": media_type, "filename": filename, "file_size_bytes": file_size_bytes,
        "candidate_count": candidate_count, "capture_source": capture_source,
        "source_notes": source_notes,
    })
    return obj


def validate_source_observation(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in SOURCE_OBSERVATION_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {SOURCE_OBSERVATION_VALIDATION_STATUSES}")
    for f in ("media_type", "filename", "file_size_bytes", "candidate_count"):
        if f not in obj:
            errors.append(f"missing required field: {f}")
    return errors


# --------------------------------------------------------------------
# 2. CapabilityCandidate -- the extracted signal for one candidate,
#    always starting at the mission's specified epistemic floor.
# --------------------------------------------------------------------

CANDIDATE_VALIDATION_STATUSES = {"unvalidated", "extracted"}


def new_capability_candidate(
    *, artifact_id: str, artifact_sha256: str, observed_name: str, normalized_name: str,
    observed_category: str, normalized_category: str, canonical_hint, maintainer_hint,
    source_observation_id: str, source_notes: str = "",
    canonical_hint_normalized=None, canonical_hint_normalization_method: str = "",
) -> dict:
    """canonical_hint is always the RAW, unmodified value observed in the
    source packet -- never rewritten. canonical_hint_normalized is a
    separately-recorded best-effort normalization (e.g. a bare
    "github.com/owner/repo" string with an assumed https:// scheme
    prepended), with canonical_hint_normalization_method stating exactly
    how it was derived. Both default to matching canonical_hint verbatim
    (method "" / not_needed) when the raw hint was already well-formed --
    see ingest.py's synthetic path -- and diverge only when the source
    packet's hint needed a stated transformation to become a URL at all
    -- see authoritative_intake.py's real 42-candidate packet, whose
    canonical_hint values arrive as bare "github.com/owner/repo" strings.
    """
    obj = common.build_envelope(
        "CAP", artifact_id, artifact_sha256, extraction_method="candidate_extraction",
        validation_status="extracted", confidence=None,
        evidence_references=[source_observation_id], human_review_status="not_required",
    )
    obj.update({
        "observed_name": observed_name,
        "normalized_name": normalized_name,
        "observed_category": observed_category,
        "normalized_category": normalized_category,
        "canonical_hint": canonical_hint,
        "canonical_hint_normalized": canonical_hint_normalized if canonical_hint_normalized is not None else canonical_hint,
        "canonical_hint_normalization_method": canonical_hint_normalization_method,
        "canonical_repository_url": None,
        "maintainer_hint": maintainer_hint,
        "maintainer_identity": None,
        "source_notes": source_notes,
        "identity_status": "UNVERIFIED",
        "safety_status": "NOT_ASSESSED",
        "license_status": "NOT_ASSESSED",
        "maintenance_status": "NOT_ASSESSED",
        "installation_status": "NOT_INSTALLED",
        "authority_status": "NOT_GRANTED",
        "promotion_status": "NOT_ELIGIBLE",
        "registry_overlap": "UNRESOLVED",
        "identity_verified_at": None,
    })
    return obj


def validate_capability_candidate(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in CANDIDATE_VALIDATION_STATUSES:
        errors.append(f"validation_status must be one of {CANDIDATE_VALIDATION_STATUSES}")
    if not obj.get("observed_name"):
        errors.append("missing required field: observed_name")
    if obj.get("identity_status") not in IDENTITY_STATES:
        errors.append(f"identity_status must be one of {IDENTITY_STATES}")
    for f in ("safety_status", "license_status", "maintenance_status"):
        if obj.get(f) not in ASSESSMENT_STATES:
            errors.append(f"{f} must be one of {ASSESSMENT_STATES}")
    if obj.get("installation_status") not in INSTALLATION_STATES:
        errors.append(f"installation_status must be one of {INSTALLATION_STATES}")
    if obj.get("authority_status") not in AUTHORITY_STATES:
        errors.append(f"authority_status must be one of {AUTHORITY_STATES}")
    if obj.get("promotion_status") not in PROMOTION_STATES:
        errors.append(f"promotion_status must be one of {PROMOTION_STATES}")
    if obj.get("registry_overlap") not in OVERLAP_STATES:
        errors.append(f"registry_overlap must be one of {OVERLAP_STATES}")
    return errors


def freshly_ingested_candidate_is_at_epistemic_floor(obj: dict) -> bool:
    """True iff every epistemic field is still at the mission's specified
    floor -- used by ingest.py to fail closed if a source packet somehow
    arrives with a candidate pre-set to a stronger state (claims-integrity
    guard: a source packet cannot assert its own verification)."""
    return (
        obj.get("identity_status") == "UNVERIFIED"
        and obj.get("safety_status") == "NOT_ASSESSED"
        and obj.get("license_status") == "NOT_ASSESSED"
        and obj.get("maintenance_status") == "NOT_ASSESSED"
        and obj.get("installation_status") == "NOT_INSTALLED"
        and obj.get("authority_status") == "NOT_GRANTED"
        and obj.get("promotion_status") == "NOT_ELIGIBLE"
    )


# --------------------------------------------------------------------
# 3. IdentityEvidence -- one identity-resolution attempt for one candidate.
# --------------------------------------------------------------------

def new_identity_evidence(
    *, artifact_id: str, artifact_sha256: str, candidate_id: str, resolver_provider: str,
    resolution: str, canonical_repository_url, canonical_owner, license_id, evidence_basis: str,
    confidence: float, raw_response=None,
) -> dict:
    if resolution not in IDENTITY_STATES:
        raise ValueError(f"resolution must be one of {IDENTITY_STATES}")
    obj = common.build_envelope(
        "IDE", artifact_id, artifact_sha256, extraction_method="identity_resolution",
        validation_status=resolution, provider=resolver_provider, raw_response=raw_response,
        confidence=confidence, evidence_references=[candidate_id],
    )
    obj.update({
        "candidate_id": candidate_id,
        "resolution": resolution,
        "canonical_repository_url": canonical_repository_url,
        "canonical_owner": canonical_owner,
        "license_id": license_id,
        "evidence_basis": evidence_basis,
    })
    return obj


def validate_identity_evidence(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("resolution") not in IDENTITY_STATES:
        errors.append(f"resolution must be one of {IDENTITY_STATES}")
    if obj.get("validation_status") != obj.get("resolution"):
        errors.append("validation_status must equal resolution")
    if not obj.get("candidate_id"):
        errors.append("missing required field: candidate_id")
    if not obj.get("evidence_basis"):
        errors.append("missing required field: evidence_basis")
    return errors


# --------------------------------------------------------------------
# 4. VerificationResult -- one safety/license/maintainability assessment.
# --------------------------------------------------------------------

VERIFICATION_DIMENSIONS = {"safety", "license", "maintainability"}


def new_verification_result(
    *, artifact_id: str, artifact_sha256: str, candidate_id: str, dimension: str,
    status: str, basis: str, confidence: float, provider: str = "capability_dispatch.verification",
) -> dict:
    if dimension not in VERIFICATION_DIMENSIONS:
        raise ValueError(f"dimension must be one of {VERIFICATION_DIMENSIONS}")
    if status not in ASSESSMENT_STATES:
        raise ValueError(f"status must be one of {ASSESSMENT_STATES}")
    obj = common.build_envelope(
        "VER", artifact_id, artifact_sha256, extraction_method=f"{dimension}_verification",
        validation_status=status, provider=provider, confidence=confidence,
        evidence_references=[candidate_id],
    )
    obj.update({"candidate_id": candidate_id, "dimension": dimension, "basis": basis})
    return obj


def validate_verification_result(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("dimension") not in VERIFICATION_DIMENSIONS:
        errors.append(f"dimension must be one of {VERIFICATION_DIMENSIONS}")
    if obj.get("validation_status") not in ASSESSMENT_STATES:
        errors.append(f"validation_status must be one of {ASSESSMENT_STATES}")
    if not obj.get("basis"):
        errors.append("missing required field: basis")
    return errors


# --------------------------------------------------------------------
# 5. RegistryOverlap -- comparison of a verified candidate against
#    capabilities/registry.json. Reuses EvidenceRelationship's shape.
# --------------------------------------------------------------------

def new_registry_overlap(
    *, artifact_id: str, artifact_sha256: str, candidate_id: str, matched_capability_ids: list,
    classification: str, shared_functions: list, missing_functions: list,
    conflicting_assumptions: list, recommended_disposition: str, confidence: float,
    basis: str = "", provider: str = "capability_dispatch.overlap",
) -> dict:
    if classification not in OVERLAP_STATES:
        raise ValueError(f"classification must be one of {OVERLAP_STATES}")
    if recommended_disposition not in DISPOSITIONS:
        raise ValueError(f"recommended_disposition must be one of {DISPOSITIONS}")
    obj = common.build_envelope(
        "OVL", artifact_id, artifact_sha256, extraction_method="registry_overlap_analysis",
        validation_status="proposed", provider=provider, confidence=confidence,
        evidence_references=[candidate_id] + list(matched_capability_ids),
    )
    obj.update({
        "candidate_id": candidate_id,
        "matched_capability_ids": list(matched_capability_ids),
        "classification": classification,
        "shared_functions": list(shared_functions),
        "missing_functions": list(missing_functions),
        "conflicting_assumptions": list(conflicting_assumptions),
        "recommended_disposition": recommended_disposition,
        "basis": basis,
    })
    return obj


def validate_registry_overlap(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("classification") not in OVERLAP_STATES:
        errors.append(f"classification must be one of {OVERLAP_STATES}")
    if obj.get("recommended_disposition") not in DISPOSITIONS:
        errors.append(f"recommended_disposition must be one of {DISPOSITIONS}")
    if not obj.get("candidate_id"):
        errors.append("missing required field: candidate_id")
    return errors


# --------------------------------------------------------------------
# 6. DispatchProfile -- the execution-surface/cost/risk profile a
#    candidate would carry IF dispatched (never implies it has been).
# --------------------------------------------------------------------

def new_dispatch_profile(
    *, artifact_id: str, artifact_sha256: str, candidate_id: str,
    supported_capability_classes: list, required_execution_surface: str,
    permission_surface: list, network_required: bool, filesystem_required: bool,
    shell_required: bool, credential_required: bool, context_requirements: list,
    latency_estimate: float, cost_estimate: float, reversibility: str,
    failure_modes: list, evidence_strength: str, freshness: str, known_conflicts: list,
) -> dict:
    obj = common.build_envelope(
        "PRF", artifact_id, artifact_sha256, extraction_method="dispatch_profile_construction",
        validation_status="proposed", confidence=None, evidence_references=[candidate_id],
    )
    obj.update({
        "candidate_id": candidate_id,
        "supported_capability_classes": list(supported_capability_classes),
        "required_execution_surface": required_execution_surface,
        "permission_surface": list(permission_surface),
        "network_required": bool(network_required),
        "filesystem_required": bool(filesystem_required),
        "shell_required": bool(shell_required),
        "credential_required": bool(credential_required),
        "context_requirements": list(context_requirements),
        "latency_estimate": latency_estimate,
        "cost_estimate": cost_estimate,
        "reversibility": reversibility,
        "failure_modes": list(failure_modes),
        "evidence_strength": evidence_strength,
        "freshness": freshness,
        "known_conflicts": list(known_conflicts),
    })
    return obj


def validate_dispatch_profile(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if not obj.get("candidate_id"):
        errors.append("missing required field: candidate_id")
    for f in ("network_required", "filesystem_required", "shell_required", "credential_required"):
        if not isinstance(obj.get(f), bool):
            errors.append(f"{f} must be a bool")
    return errors


def is_unbounded_execution_surface(profile: dict) -> bool:
    """True when a profile requires shell + credentials + network with no
    declared reversibility -- the mission's UNBOUNDED_EXECUTION_SURFACE
    hard-block condition, made checkable rather than left as prose."""
    return (
        profile.get("shell_required") and profile.get("credential_required")
        and profile.get("network_required") and profile.get("reversibility") in (None, "", "irreversible")
    )


# --------------------------------------------------------------------
# 7. DispatchDecision -- the mission-level record. Superset-compatible
#    with router.mission_router.route()'s existing decision shape (see
#    dispatch.py) so router/decisions.jsonl stays one ledger.
# --------------------------------------------------------------------

DECISION_STATUSES = {"HARD_BLOCKED", "DISPATCHED", "NO_SUFFICIENT_CANDIDATE"}


def new_dispatch_decision(
    *, mission_id: str, run_id: str, problem_statement, root_cause_hypothesis, desired_outcome,
    success_metric, required_capabilities: list, considered_candidate_ids: list,
    rejected: list, selected_set: list, authority_decision, risk_decision, overlap_decision,
    sandbox_requirements: list, expected_evidence: str, execution_result, confidence,
    unresolved_questions: list, status: str, hard_block_reason=None,
) -> dict:
    if status not in DECISION_STATUSES:
        raise ValueError(f"status must be one of {DECISION_STATUSES}")
    if hard_block_reason is not None and hard_block_reason not in HARD_BLOCK_REASONS:
        raise ValueError(f"hard_block_reason must be one of {HARD_BLOCK_REASONS} or None")
    obj = common.build_envelope(
        "DEC", mission_id, None, extraction_method="dispatch_decision",
        validation_status=status, confidence=confidence,
        evidence_references=list(considered_candidate_ids),
        human_review_status="not_required" if status == "HARD_BLOCKED" else "pending",
    )
    obj.update({
        "mission_id": mission_id,
        "run_id": run_id,
        "problem_statement": problem_statement,
        "root_cause_hypothesis": root_cause_hypothesis,
        "desired_outcome": desired_outcome,
        "success_metric": success_metric,
        "required_capabilities": list(required_capabilities),
        "considered_candidate_ids": list(considered_candidate_ids),
        "rejected": list(rejected),
        "selected_set": list(selected_set),
        "authority_decision": authority_decision,
        "risk_decision": risk_decision,
        "overlap_decision": overlap_decision,
        "sandbox_requirements": list(sandbox_requirements),
        "expected_evidence": expected_evidence,
        "execution_result": execution_result,
        "unresolved_questions": list(unresolved_questions),
        "hard_block_reason": hard_block_reason,
    })
    return obj


def validate_dispatch_decision(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if obj.get("validation_status") not in DECISION_STATUSES:
        errors.append(f"validation_status must be one of {DECISION_STATUSES}")
    if obj.get("validation_status") == "HARD_BLOCKED" and obj.get("hard_block_reason") not in HARD_BLOCK_REASONS:
        errors.append(f"a HARD_BLOCKED decision must carry a hard_block_reason from {HARD_BLOCK_REASONS}")
    if not obj.get("mission_id"):
        errors.append("missing required field: mission_id")
    return errors


# --------------------------------------------------------------------
# 8. DispatchLearningRecord -- predicted vs. observed, folded into
#    router.record_outcome's existing 4-field schema at the write site
#    (see learning.py); this richer shape is what feeds that call.
# --------------------------------------------------------------------

def new_dispatch_learning_record(
    *, artifact_id: str, artifact_sha256: str, decision_id: str, candidate_id: str,
    predicted_utility: float, observed_utility, predicted_cost: float, observed_cost,
    predicted_latency: float, observed_latency, expected_outcome: str, measured_outcome,
    failure_classification, rollback_result, evidence_sufficiency: str,
    routing_policy_delta, promotion_decision,
) -> dict:
    obj = common.build_envelope(
        "LRN", artifact_id, artifact_sha256, extraction_method="dispatch_learning_record",
        validation_status="recorded", confidence=None, evidence_references=[decision_id, candidate_id],
    )
    obj.update({
        "decision_id": decision_id, "candidate_id": candidate_id,
        "predicted_utility": predicted_utility, "observed_utility": observed_utility,
        "predicted_cost": predicted_cost, "observed_cost": observed_cost,
        "predicted_latency": predicted_latency, "observed_latency": observed_latency,
        "expected_outcome": expected_outcome, "measured_outcome": measured_outcome,
        "failure_classification": failure_classification, "rollback_result": rollback_result,
        "evidence_sufficiency": evidence_sufficiency,
        "routing_policy_delta": routing_policy_delta, "promotion_decision": promotion_decision,
    })
    return obj


def validate_dispatch_learning_record(obj: dict) -> list:
    errors = common.validate_envelope(obj)
    if not obj.get("decision_id"):
        errors.append("missing required field: decision_id")
    if not obj.get("candidate_id"):
        errors.append("missing required field: candidate_id")
    return errors


VALIDATORS = {
    "SourceObservation": validate_source_observation,
    "CapabilityCandidate": validate_capability_candidate,
    "IdentityEvidence": validate_identity_evidence,
    "VerificationResult": validate_verification_result,
    "RegistryOverlap": validate_registry_overlap,
    "DispatchProfile": validate_dispatch_profile,
    "DispatchDecision": validate_dispatch_decision,
    "DispatchLearningRecord": validate_dispatch_learning_record,
}
