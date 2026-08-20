"""CONTEXT-COMPILATION BEHAVIOR.

Builds the smallest sufficient working context for one DispatchDecision --
never the entire capability registry, full conversation history, or every
installed skill. Every object included is recorded with a one-line reason
it was selected, converting the knowledge base from "load everything and
hope" into an addressable evidence graph, per the mission's own framing.

Deliberately reads narrowly: governance.authority.load_policies() is
filtered to only the capability strings this decision actually checked
(not the full policy table), and capabilities/registry.json is filtered
to only the capability IDs a selected candidate actually matched (not the
full registry).
"""
from governance.authority import load_policies

from whatsapp.src import ledger as wa_ledger

from .common import now_iso


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def compile_context(decision: dict, mission_request: dict, candidate_bundles: list) -> dict:
    """Returns the minimal context bundle for `decision`, plus a
    `selection_rationale` mapping every included object's id/key to why it
    was pulled in -- so the compiled context is itself auditable, not a
    black box."""
    selected_ids = {s["candidate_id"] for s in decision["selected_set"] if s["candidate_id"] is not None}
    selected_bundles = [b for b in candidate_bundles if b["candidate"]["id"] in selected_ids]
    reused_existing_ids = [
        s["existing_capability_id"] for s in decision["selected_set"]
        if s.get("existing_capability_id")
    ]

    rationale = {}

    active_mission = {
        "mission_id": decision["mission_id"],
        "problem_statement": decision["problem_statement"],
        "desired_outcome": decision["desired_outcome"],
        "success_metric": decision["success_metric"],
    }
    rationale["active_mission"] = "the mission this decision was made for -- always included"

    capabilities_checked = {"SANDBOX_PROBE_CANDIDATE"} if selected_bundles else set()
    all_policies = load_policies()
    required_authority_rules = [
        {"policy_id": p.policy_id, "capability": p.capability, "decision": p.decision.value}
        for p in all_policies if p.capability in capabilities_checked
    ]
    for r in required_authority_rules:
        rationale[r["policy_id"]] = f"authority policy actually checked for capability {r['capability']!r} in this decision"

    selected_capability_instructions = []
    directly_relevant_evidence = []
    necessary_project_context = []
    for existing_id in reused_existing_ids:
        necessary_project_context.append(f"capabilities/registry.json:{existing_id}")
        rationale[f"capabilities/registry.json:{existing_id}"] = "reused directly to satisfy a required capability -- no candidate evidence needed"
    for b in selected_bundles:
        cand = b["candidate"]
        selected_capability_instructions.append({
            "candidate_id": cand["id"], "observed_name": cand["observed_name"],
            "disposition": next(s["disposition"] for s in decision["selected_set"] if s["candidate_id"] == cand["id"]),
            "canonical_repository_url": cand.get("canonical_repository_url"),
        })
        rationale[cand["id"]] = "selected into the smallest sufficient set for this mission"

        directly_relevant_evidence.append(b["identity_evidence"]["id"])
        rationale[b["identity_evidence"]["id"]] = f"identity evidence for selected candidate {cand['id']}"
        directly_relevant_evidence.append(b["overlap"]["id"])
        rationale[b["overlap"]["id"]] = f"registry overlap analysis for selected candidate {cand['id']}"
        for v in b.get("verification_results", []):
            directly_relevant_evidence.append(v["id"])
            rationale[v["id"]] = f"{v['dimension']} verification for selected candidate {cand['id']}"

        for matched_id in b["overlap"]["matched_capability_ids"]:
            necessary_project_context.append(f"capabilities/registry.json:{matched_id}")
            rationale[f"capabilities/registry.json:{matched_id}"] = (
                f"the existing registered capability {cand['id']}'s overlap analysis matched against"
            )

    applicable_constraints = []
    if decision["validation_status"] == "HARD_BLOCKED":
        applicable_constraints = [decision["hard_block_reason"]]
        rationale[decision["hard_block_reason"]] = "the hard-block reason this decision terminated on"

    output_verification_contract = {
        "expected_evidence": decision["expected_evidence"],
        "sandbox_requirements": decision["sandbox_requirements"],
    }

    context = {
        "active_mission": active_mission,
        "required_authority_rules": required_authority_rules,
        "selected_capability_instructions": selected_capability_instructions,
        "directly_relevant_evidence": directly_relevant_evidence,
        "necessary_project_context": necessary_project_context,
        "applicable_constraints": applicable_constraints,
        "output_verification_contract": output_verification_contract,
        "selection_rationale": rationale,
    }

    _record(
        "CONTEXT_COMPILATION", decision_id=decision["id"],
        object_count=len(rationale), selected_candidate_count=len(selected_bundles), state="COMPILED",
    )
    return context
