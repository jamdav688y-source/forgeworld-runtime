"""DYNAMIC DISPATCH ENGINE.

Extends router/mission_router.py -- imported and called directly
(score_capability, historical_stats, cost_score are reused verbatim for
any candidate whose RegistryOverlap matched an existing registered
capability) -- rather than reimplementing capability scoring. What this
module adds on top, because mission_router.route() cannot do it:

  * evaluates a CapabilityCandidate (identity/overlap/profile/verification
    all still epistemic, not an already-decided registry entry) instead of
    only an already-registered capability;
  * assigns one of seven dispositions (REUSE/ADAPT/SANDBOX_PROBE/OBSERVE/
    DUPLICATE/REJECT/BLOCK) via an explicit, ordered, auditable decision
    tree -- never a single opaque score;
  * selects the SMALLEST SUFFICIENT SET of capabilities covering a
    mission's required_capabilities, not the single best-scoring one;
  * writes an extended DispatchDecision into the SAME router/decisions.jsonl
    mission_router.route() already writes to (superset of its fields, so
    the ledger stays one file, not two).

Every exclusion carries its own reason; there is no code path that drops a
candidate from the selected set without recording why.
"""
import json

from governance.authority import evaluate_authority
from governance.types import AuthorityState, EvidenceState, EVIDENCE_STATE_ORDER
from router import mission_router

from . import gate, schema
from .common import now_iso

ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC"}

SANDBOX_PROBE_CAPABILITY = "SANDBOX_PROBE_CANDIDATE"
SANDBOX_PROBE_TARGET = {"resource": "capability_candidate", "target": "*"}

VERIFICATION_DIMENSIONS_REQUIRED_FOR_PROBE = {"safety", "license", "maintainability"}


def _evidence_score(state: EvidenceState) -> float:
    return EVIDENCE_STATE_ORDER.index(state) / (len(EVIDENCE_STATE_ORDER) - 1)


def _record(stage: str, **fields) -> None:
    from whatsapp.src import ledger as wa_ledger
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def score_candidate(candidate: dict, identity_evidence: dict, overlap: dict,
                     profile, verification_results: list, reachability_state: dict = None) -> dict:
    """Component scores -- never collapsed into one number. Every
    component is independently inspectable and independently excludable.

    `reachability_state` is optional and, when supplied, is used instead
    of calling capabilities.discover.probe_all() -- which performs a real
    TCP connection attempt for any registered capability with a "network"
    check (e.g. github: api.github.com:443). Tests always supply a
    deterministic fixture dict here so no test run ever touches the
    network (mission Section 14: "Do not use live external repositories
    in unit tests"); real dispatch runs may omit it and let probe_all()
    measure live reachability, exactly like mission_router.route() already
    does.
    """
    verified_dims = {v["dimension"]: v["validation_status"] for v in verification_results}

    components = {
        "identity_confidence": identity_evidence.get("confidence", 0.0) if identity_evidence.get("resolution") == "VERIFIED" else 0.0,
        "safety": {"PASSED": 1.0, "NOT_ASSESSED": 0.5, "INCONCLUSIVE": 0.3, "FAILED": 0.0}.get(verified_dims.get("safety", "NOT_ASSESSED"), 0.5),
        "license": {"PASSED": 1.0, "NOT_ASSESSED": 0.5, "INCONCLUSIVE": 0.3, "FAILED": 0.0}.get(verified_dims.get("license", "NOT_ASSESSED"), 0.5),
        "maintainability": {"PASSED": 1.0, "NOT_ASSESSED": 0.5, "INCONCLUSIVE": 0.3, "FAILED": 0.0}.get(verified_dims.get("maintainability", "NOT_ASSESSED"), 0.5),
        "registry_overlap_fit": {
            "UNIQUE_GAP": 0.6, "PARTIAL_OVERLAP": 0.8, "FUNCTIONAL_DUPLICATE": 0.1,
            "ARCHITECTURAL_CONFLICT": 0.0, "UNRESOLVED": 0.0,
        }.get(overlap["classification"], 0.0),
        "reversibility": 1.0 if profile and profile.get("reversibility") == "reversible" else 0.0,
        "cost": 1.0 - min(1.0, profile.get("cost_estimate", 1.0)) if profile else 0.5,
        "latency": 1.0 - min(1.0, (profile.get("latency_estimate", 1.0) or 0.0) / 10.0) if profile else 0.5,
    }

    if overlap["matched_capability_ids"]:
        registry = mission_router.load_registry()
        reach = reachability_state if reachability_state is not None else mission_router.discover.probe_all()
        history = mission_router.load_history()
        matched = next((c for c in registry if c["id"] == overlap["matched_capability_ids"][0]), None)
        if matched is not None:
            existing_score = mission_router.score_capability(matched, [], reach, history)
            components["prior_verified_performance"] = existing_score["confidence"]["historical_evidence"]
            components["existing_capability_reachability"] = existing_score["confidence"]["reachability"]

    return components


def _classify_disposition(candidate: dict, identity_evidence: dict, overlap: dict,
                           profile, verification_results: list, authority_envelope: str) -> dict:
    """Ordered, auditable decision tree. Exactly one branch fires. Returns
    {"disposition": ..., "hard_block": HardBlock-or-None, "reasoning": str}."""
    verified_dims = {v["dimension"]: v["validation_status"] for v in verification_results}

    if candidate["identity_status"] != "VERIFIED":
        return {
            "disposition": "BLOCK",
            "hard_block": gate.hard_block(
                "IDENTITY_AMBIGUOUS_FOR_INSTALL",
                f"identity_status={candidate['identity_status']} (resolution basis: "
                f"{identity_evidence.get('evidence_basis', 'n/a')}) -- an unverified or "
                f"ambiguous candidate cannot become installable or dispatch-eligible.",
                gate.CATEGORY_EVIDENCE_INSUFFICIENCY,
            ),
            "reasoning": "identity not VERIFIED",
        }

    if overlap["classification"] == "ARCHITECTURAL_CONFLICT":
        return {
            "disposition": "BLOCK",
            "hard_block": gate.hard_block(
                "ARCHITECTURAL_CONFLICT", overlap.get("basis", ""), gate.CATEGORY_GOVERNANCE_REJECTION,
            ),
            "reasoning": "registry overlap analysis found an architectural conflict",
        }

    if profile is not None and schema.is_unbounded_execution_surface(profile):
        return {
            "disposition": "BLOCK",
            "hard_block": gate.hard_block(
                "UNBOUNDED_EXECUTION_SURFACE",
                f"profile requires shell={profile['shell_required']}, "
                f"credentials={profile['credential_required']}, network={profile['network_required']}, "
                f"reversibility={profile.get('reversibility')!r} -- unbounded, irreversible execution "
                f"surface is never dispatch-eligible regardless of popularity or apparent utility.",
                gate.CATEGORY_GOVERNANCE_REJECTION,
            ),
            "reasoning": "unbounded execution surface",
        }

    license_id = identity_evidence.get("license_id")
    if license_id is not None and license_id not in ALLOWED_LICENSES:
        return {
            "disposition": "BLOCK",
            "hard_block": gate.hard_block(
                "LICENSE_INCOMPATIBLE", f"license {license_id!r} is not in the allowed set {sorted(ALLOWED_LICENSES)}",
                gate.CATEGORY_GOVERNANCE_REJECTION,
            ),
            "reasoning": "license not in allowed set",
        }

    if verified_dims.get("safety") == "FAILED":
        return {
            "disposition": "BLOCK",
            "hard_block": gate.hard_block(
                "SECURITY_REVIEW_FAILED", "safety VerificationResult status is FAILED",
                gate.CATEGORY_GOVERNANCE_REJECTION,
            ),
            "reasoning": "safety verification failed",
        }

    if overlap["classification"] == "FUNCTIONAL_DUPLICATE":
        return {"disposition": "DUPLICATE", "hard_block": None, "reasoning": overlap.get("basis", "")}

    if overlap["classification"] == "PARTIAL_OVERLAP":
        return {"disposition": "ADAPT", "hard_block": None, "reasoning": overlap.get("basis", "")}

    if overlap["classification"] == "UNIQUE_GAP":
        if authority_envelope not in ("GRANTED", "GRANTED_BOUNDED"):
            return {
                "disposition": "BLOCK",
                "hard_block": gate.hard_block(
                    "AUTHORITY_NOT_GRANTED",
                    "candidate is a technically viable unique-gap capability but no authority "
                    "was granted for SANDBOX_PROBE_CANDIDATE this mission (PRODUCTION_PROMOTION_AUTHORITY "
                    "and THIRD_PARTY_INSTALLATION_AUTHORITY were both explicitly withheld).",
                    gate.CATEGORY_GOVERNANCE_REJECTION,
                ),
                "reasoning": "no authority granted",
            }
        missing_verification = VERIFICATION_DIMENSIONS_REQUIRED_FOR_PROBE - {
            d for d, s in verified_dims.items() if s == "PASSED"
        }
        if missing_verification:
            return {
                "disposition": "OBSERVE",
                "hard_block": None,
                "reasoning": f"unique gap, authority present, but verification incomplete: missing PASSED for {sorted(missing_verification)}",
            }
        if profile is None or profile.get("reversibility") != "reversible":
            return {
                "disposition": "BLOCK",
                "hard_block": gate.hard_block(
                    "INSUFFICIENT_EVIDENCE",
                    "no DispatchProfile, or profile does not declare reversibility -- a sandbox "
                    "probe requires a known-reversible execution surface.",
                    gate.CATEGORY_EVIDENCE_INSUFFICIENCY,
                ),
                "reasoning": "no reversible profile for probe",
            }
        return {"disposition": "SANDBOX_PROBE", "hard_block": None, "reasoning": "fully verified unique gap, authority present, reversible"}

    # overlap == UNRESOLVED reaches here only if identity was VERIFIED but
    # overlap.py still returned UNRESOLVED -- defensive fallback, should
    # not occur given overlap.py's own identity gate, but never silently
    # falls through to an implicit REUSE/ADAPT.
    return {
        "disposition": "BLOCK",
        "hard_block": gate.hard_block(
            "INSUFFICIENT_EVIDENCE", f"unexpected overlap classification {overlap['classification']!r} for a VERIFIED candidate",
            gate.CATEGORY_TECHNICAL_FAILURE,
        ),
        "reasoning": "unresolved overlap for verified candidate",
    }


def evaluate_candidate(candidate: dict, identity_evidence: dict, overlap: dict, profile,
                        verification_results: list, decided_by: str, reachability_state: dict = None) -> dict:
    """Runs the SANDBOX_PROBE authority check (governance.authority,
    reused directly) when relevant, classifies disposition, and returns
    the full evaluation record used by select_smallest_sufficient_set()."""
    authority_decision = evaluate_authority(
        actor_id=decided_by, capability=SANDBOX_PROBE_CAPABILITY, target=SANDBOX_PROBE_TARGET,
        context={"crosses_external_boundary": False},
    )
    envelope = (
        "GRANTED" if authority_decision.decision == AuthorityState.ALLOWED
        else "GRANTED_BOUNDED" if authority_decision.decision == AuthorityState.ALLOWED_BOUNDED
        else "NOT_GRANTED"
    )

    result = _classify_disposition(candidate, identity_evidence, overlap, profile, verification_results, envelope)
    components = score_candidate(candidate, identity_evidence, overlap, profile, verification_results, reachability_state)

    _record(
        "DISPATCH_EVALUATION", candidate_id=candidate["id"], disposition=result["disposition"],
        authority_decision=authority_decision.decision.value, component_scores=components,
        reasoning=result["reasoning"], state="EVALUATED",
    )

    return {
        "candidate": candidate, "disposition": result["disposition"], "hard_block": result["hard_block"],
        "reasoning": result["reasoning"], "component_scores": components,
        "authority_decision": authority_decision.decision.value, "overlap": overlap,
    }


def select_smallest_sufficient_set(evaluations: list, required_capabilities: list) -> dict:
    """Greedy set cover: for each required capability class, pick the
    single best-scoring eligible candidate (REUSE/ADAPT/SANDBOX_PROBE
    only -- OBSERVE/DUPLICATE/REJECT/BLOCK are never selected for
    execution) that covers it, by descending mean component score. Stops
    as soon as every required capability is covered by at least one
    selection -- this is deliberately the SMALLEST sufficient set, not the
    largest available one.
    """
    from . import overlap as overlap_mod

    eligible_dispositions = {"REUSE", "ADAPT", "SANDBOX_PROBE"}
    selected = []
    rejected = []
    covered = set()

    def mean_score(ev):
        vals = ev["component_scores"].values()
        return sum(vals) / len(vals) if vals else 0.0

    # Smallest sufficient set, step 1: an already-registered capability
    # that already covers a required capability class needs NO candidate
    # at all -- selecting a new candidate when the registry already
    # satisfies the requirement would grow the toolset, not minimize it.
    registry = mission_router.load_registry()
    for req in required_capabilities:
        req_tags = overlap_mod.CATEGORY_FUNCTION_TAGS.get(req, {req})
        existing = next((cap for cap in registry if req_tags & set(cap.get("tags", []))), None)
        if existing is not None:
            selected.append({
                "candidate": None, "disposition": "REUSE",
                "reasoning": f"required capability {req!r} is already covered by registered capability '{existing['id']}' -- no new candidate needed",
                "component_scores": {"reuse_existing": 1.0}, "authority_decision": "NOT_REQUIRED",
                "overlap": None, "existing_capability_id": existing["id"],
            })
            covered.add(req)

    # Step 2: only for requirements the registry does NOT already cover,
    # consider evaluated candidates.
    ranked = sorted(
        [e for e in evaluations if e["disposition"] in eligible_dispositions],
        key=mean_score, reverse=True,
    )
    for req in required_capabilities:
        if req in covered:
            continue
        match = next(
            (e for e in ranked
             if req in e["candidate"]["normalized_category"]),
            None,
        )
        if match is not None:
            selected.append(match)
            covered.add(req)

    selected_candidate_ids = {s["candidate"]["id"] for s in selected if s["candidate"] is not None}
    for e in evaluations:
        if e["candidate"]["id"] not in selected_candidate_ids:
            rejected.append({
                "candidate_id": e["candidate"]["id"], "observed_name": e["candidate"]["observed_name"],
                "disposition": e["disposition"], "reasoning": e["reasoning"],
            })

    return {
        "selected": selected, "rejected": rejected,
        "required_capabilities": list(required_capabilities), "covered": sorted(covered),
        "fully_satisfied": covered.issuperset(required_capabilities),
    }


def write_decision(decision: dict) -> None:
    """Appends into the SAME router/decisions.jsonl mission_router.route()
    already writes to -- mission_router.DECISIONS_PATH is imported, not
    redefined, so there is exactly one source of truth for this path."""
    with open(mission_router.DECISIONS_PATH, "a") as f:
        f.write(json.dumps(decision, default=str) + "\n")


def run_dispatch(
    mission_request: dict, run_id: str, source_observation, candidate_bundles: list, decided_by: str,
    reachability_state: dict = None,
) -> dict:
    """Top-level orchestration: PROBLEM-FIRST GATE -> per-candidate
    evaluation -> SMALLEST SUFFICIENT SET -> DispatchDecision, written to
    router/decisions.jsonl. `candidate_bundles` is a list of
    {"candidate", "identity_evidence", "overlap", "profile", "verification_results"}
    dicts, one per candidate already carried through
    ingest -> identity -> overlap (and, optionally, verification/profile
    construction) upstream of this call -- this function does not itself
    ingest or resolve identity, keeping each pipeline stage independently
    testable.
    """
    mission_id = mission_request.get("mission_id", "FW-CAP-DISPATCH-004")
    artifact_id = source_observation["source_artifact_id"] if source_observation else mission_id
    artifact_sha256 = source_observation["source_artifact_sha256"] if source_observation else None

    gated = gate.check_problem_first_gate(mission_request)
    if not gate.gate_passed(gated):
        decision = schema.new_dispatch_decision(
            mission_id=mission_id, run_id=run_id,
            problem_statement=mission_request.get("problem_statement"),
            root_cause_hypothesis=mission_request.get("root_cause_hypothesis"),
            desired_outcome=mission_request.get("desired_outcome"),
            success_metric=mission_request.get("success_metric"),
            required_capabilities=mission_request.get("required_capabilities", []),
            considered_candidate_ids=[], rejected=[], selected_set=[],
            authority_decision="NOT_CHECKED", risk_decision="NOT_CHECKED", overlap_decision="NOT_CHECKED",
            sandbox_requirements=[], expected_evidence="", execution_result=None, confidence=None,
            unresolved_questions=[gated["detail"]], status="HARD_BLOCKED",
            hard_block_reason=gated["hard_block_reason"],
        )
        errors = schema.validate_dispatch_decision(decision)
        if errors:
            raise ValueError(f"DispatchDecision failed validation: {errors}")
        write_decision(decision)
        _record("DISPATCH_DECISION", mission_id=mission_id, decision_id=decision["id"],
                status="HARD_BLOCKED", hard_block_reason=gated["hard_block_reason"], state="DECIDED")
        return decision

    required_capabilities = gated.get("required_capabilities", [])
    evaluations = [
        evaluate_candidate(
            b["candidate"], b["identity_evidence"], b["overlap"], b.get("profile"),
            b.get("verification_results", []), decided_by, reachability_state,
        )
        for b in candidate_bundles
    ]

    selection = select_smallest_sufficient_set(evaluations, required_capabilities)
    status = "DISPATCHED" if selection["fully_satisfied"] else "NO_SUFFICIENT_CANDIDATE"

    decision = schema.new_dispatch_decision(
        mission_id=mission_id, run_id=run_id,
        problem_statement=gated["problem_statement"], root_cause_hypothesis=gated.get("root_cause_hypothesis"),
        desired_outcome=gated["desired_outcome"], success_metric=gated["success_metric"],
        required_capabilities=required_capabilities,
        considered_candidate_ids=[e["candidate"]["id"] for e in evaluations],
        rejected=selection["rejected"],
        selected_set=[
            {
                "candidate_id": e["candidate"]["id"] if e["candidate"] else None,
                "observed_name": e["candidate"]["observed_name"] if e["candidate"] else None,
                "existing_capability_id": e.get("existing_capability_id"),
                "disposition": e["disposition"],
            }
            for e in selection["selected"]
        ],
        authority_decision=[e["authority_decision"] for e in evaluations],
        risk_decision=[e["disposition"] for e in evaluations],
        overlap_decision=[e["overlap"]["classification"] for e in evaluations],
        sandbox_requirements=[
            e["candidate"]["id"] for e in evaluations if e["disposition"] == "SANDBOX_PROBE"
        ],
        expected_evidence="sandbox probe execution log + governance.evidence OBSERVED record, if any SANDBOX_PROBE candidate is later authorized to run",
        execution_result=None,  # this mission grants no execution authority -- see Third-Party Safety Boundary
        confidence=(
            sum(sum(e["component_scores"].values()) / len(e["component_scores"]) for e in selection["selected"])
            / len(selection["selected"])
        ) if selection["selected"] else 0.0,
        unresolved_questions=[
            f"{r['observed_name']}: {r['disposition']} -- {r['reasoning']}" for r in selection["rejected"]
        ],
        status=status,
    )
    errors = schema.validate_dispatch_decision(decision)
    if errors:
        raise ValueError(f"DispatchDecision failed validation: {errors}")
    write_decision(decision)

    _record(
        "DISPATCH_DECISION", mission_id=mission_id, decision_id=decision["id"], status=status,
        selected_count=len(selection["selected"]), rejected_count=len(selection["rejected"]), state="DECIDED",
    )
    return decision
