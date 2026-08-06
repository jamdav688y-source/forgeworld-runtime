"""Capability Negotiation Engine.

Determines whether the current execution environment can complete a
named mission BEFORE execution begins, by comparing live-probed
capability evidence (via capabilities/discover.py) against a mission's
declared requirements (capability_negotiation/missions.py).

Governance, enforced structurally (not by a flag):
  - This module never writes to capabilities/registry.json. It cannot
    register a capability as available -- only capabilities/discover.py's
    probes (or evidence explicitly supplied by the calling agent) can.
  - It has no method that marks a capability AVAILABLE without either a
    successful probe or caller-supplied live evidence.
  - `policy_overrides` can only ever move a capability's state to
    BLOCKED_BY_POLICY (make things *harder* to use) -- there is no
    override argument that can force AVAILABLE.
Evidence always overrides assumptions: every state this engine assigns
carries the evidence string the probe actually produced.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

CAP_NEG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CAP_NEG_ROOT.parent
CAPABILITIES_DIR = REPO_ROOT / "capabilities"
REPORTS_DIR = CAP_NEG_ROOT / "reports"

sys.path.insert(0, str(CAPABILITIES_DIR))
sys.path.insert(0, str(CAP_NEG_ROOT))
import discover  # noqa: E402
from states import (  # noqa: E402
    AVAILABLE, UNAVAILABLE, UNKNOWN, BLOCKED_BY_POLICY, OPERATOR_REQUIRED,
    DISCOVERED_AFTER_STARTUP, BLOCKED_BY_PLATFORM, DELEGATE_TO_WINDOWS,
    SATISFIED_STATES, CHECK_TYPE_TO_DEFAULT_GAP, GAP_MISSING_OPERATOR_AUTHORIZATION,
    RESUME_READY, RESUME_STILL_BLOCKED, RESUME_NO_PRIOR_GAP,
)
from missions import get_mission  # noqa: E402


@dataclass
class RequirementResult:
    capability_id: str
    state: str
    evidence: str
    gap_class: str | None
    resolution_action: str | None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class NegotiationResult:
    mission_id: str
    objective: str
    generated_at: str
    requirements: list[RequirementResult]
    can_proceed: bool
    gaps: list[RequirementResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "objective": self.objective,
            "generated_at": self.generated_at,
            "can_proceed": self.can_proceed,
            "requirements": [r.as_dict() for r in self.requirements],
            "gaps": [g.as_dict() for g in self.gaps],
        }


def _load_registry_by_id() -> dict:
    return {cap["id"]: cap for cap in discover.load_registry()}


def _resolve_state(cap_id: str, registry_by_id: dict, probe: dict, policy_overrides: dict) -> RequirementResult:
    if cap_id in policy_overrides:
        return RequirementResult(
            capability_id=cap_id, state=BLOCKED_BY_POLICY,
            evidence=policy_overrides[cap_id], gap_class="missing_operator_authorization",
            resolution_action=f"Governance policy blocks '{cap_id}' for this mission: {policy_overrides[cap_id]}. "
                               "An operator must explicitly lift this policy override to proceed.",
        )

    entry = registry_by_id.get(cap_id)
    if entry is None:
        return RequirementResult(
            capability_id=cap_id, state=UNKNOWN,
            evidence=f"'{cap_id}' is not a registered capability in capabilities/registry.json",
            gap_class="missing_dependency",
            resolution_action=f"Register '{cap_id}' in capabilities/registry.json with a real check before this mission can be negotiated.",
        )

    check_type = entry["check"].get("type")
    p = probe.get(cap_id, {})
    confidence = p.get("reachability_confidence", 0.0)
    evidence = p.get("evidence", "not probed")

    if check_type == "self" or confidence >= 1.0:
        return RequirementResult(cap_id, AVAILABLE, evidence, None, None)

    if check_type == "connector" and "no live connector list supplied" in evidence:
        return RequirementResult(
            capability_id=cap_id, state=OPERATOR_REQUIRED, evidence=evidence,
            gap_class=GAP_MISSING_OPERATOR_AUTHORIZATION,
            resolution_action=f"Connect/authorize the '{entry['check']['value']}' connector, or have the calling "
                               f"agent supply live connector evidence when negotiating this mission.",
        )

    if confidence <= 0.0:
        gap = CHECK_TYPE_TO_DEFAULT_GAP.get(check_type, "missing_dependency")
        # A 'platform' check failure is always a deterministic cross-platform
        # mismatch, not a generic "not installed" gap -- label it precisely
        # so the resolution action reads as "run this on the right machine,"
        # not "install something here."
        state = BLOCKED_BY_PLATFORM if check_type == "platform" else UNAVAILABLE
        return RequirementResult(
            capability_id=cap_id, state=state, evidence=evidence,
            gap_class=gap, resolution_action=_resolution_action_for(cap_id, entry, gap, evidence),
        )

    return RequirementResult(
        capability_id=cap_id, state=UNKNOWN, evidence=evidence,
        gap_class="missing_dependency",
        resolution_action=f"Reachability of '{cap_id}' could not be conclusively determined ({evidence}); "
                           "an operator should confirm it directly.",
    )


def _resolution_action_for(cap_id: str, entry: dict, gap_class: str, evidence: str) -> str:
    check = entry["check"]
    if gap_class == "missing_executable":
        return f"Install and put '{check['value']}' on PATH, then re-run negotiation."
    if gap_class == "missing_dependency" and check.get("type") == "env":
        return f"Set the '{check['value']}' environment variable, then re-run negotiation."
    if gap_class == "missing_connector":
        return f"Connect the '{check['value']}' connector/service, then re-run negotiation with that evidence supplied."
    if gap_class == "missing_filesystem_access":
        return (f"This capability requires running on {check['value']} -- it cannot be satisfied from the "
                f"current platform. Execute the mission (or this specific step) on a real {check['value']} machine.")
    if gap_class == "missing_runtime" and check.get("type") == "termux":
        return ("This capability requires running inside Termux on the actual Android device -- it cannot be "
                "satisfied from any other environment, including this one. Run negotiation from within Termux "
                "on the phone itself (`python3 capability_negotiation/negotiate.py ...` under Termux, once the "
                "repo is cloned there).")
    return f"Resolve: {evidence}"


def _delegated_result(cap_id: str, registry_by_id: dict) -> RequirementResult:
    """A mission-level policy decision, not a probe result: this
    capability is never attempted on this device, by design -- it always
    routes to Windows via a mission_handoff package. Unlike
    BLOCKED_BY_POLICY (which blocks a mission), DELEGATE_TO_WINDOWS is a
    complete, intended resolution and counts as satisfied."""
    known = registry_by_id.get(cap_id) is not None
    evidence = (
        f"'{cap_id}' is declared out of scope for this device by mission design"
        + ("" if known else f" (not found in capabilities/registry.json either -- register it if it needs its own probe)")
    )
    return RequirementResult(
        capability_id=cap_id, state=DELEGATE_TO_WINDOWS, evidence=evidence,
        gap_class=None,
        resolution_action="Execute via a mission_handoff package addressed to the Windows runtime "
                           "(see forgeworld-mobile-research/mission_handoff.py); no local action needed.",
    )


def negotiate(mission_id: str, live_connectors: list[str] | None = None,
              policy_overrides: dict | None = None) -> NegotiationResult:
    """Runs the full discover -> compare -> classify -> decide pipeline for
    one mission. Never fabricates a capability: every AVAILABLE state
    traces back to a probe result or explicitly-supplied live evidence."""
    mission = get_mission(mission_id)
    registry_by_id = _load_registry_by_id()
    probe = discover.probe_all(live_connectors=live_connectors)
    policy_overrides = policy_overrides or {}

    delegated_ids = set(mission.get("delegate_to_windows_ids", []))
    requirements = [
        _resolve_state(cap_id, registry_by_id, probe, policy_overrides)
        for cap_id in mission["required_capability_ids"]
        if cap_id not in delegated_ids
    ] + [
        _delegated_result(cap_id, registry_by_id) for cap_id in delegated_ids
    ]
    gaps = [r for r in requirements if r.state not in SATISFIED_STATES]
    can_proceed = len(gaps) == 0

    return NegotiationResult(
        mission_id=mission_id,
        objective=mission["objective"],
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        requirements=requirements,
        can_proceed=can_proceed,
        gaps=gaps,
    )


def generate_operator_actions_md(result: NegotiationResult) -> str:
    lines = [
        f"# Operator Actions -- {result.mission_id}",
        "",
        f"Mission status: {'READY' if result.can_proceed else 'BLOCKED'}",
        f"Objective: {result.objective}",
        f"Generated: {result.generated_at}",
        "",
    ]
    if result.can_proceed:
        lines.append("No operator action required -- every declared requirement is satisfied.")
    else:
        lines.append(f"{len(result.gaps)} capability gap(s) must be resolved before this mission can proceed:")
        lines.append("")
        for i, gap in enumerate(result.gaps, start=1):
            lines += [
                f"## {i}. {gap.capability_id} -- {gap.state}",
                f"- gap class: `{gap.gap_class}`",
                f"- evidence: {gap.evidence}",
                f"- required operator action: {gap.resolution_action}",
                "",
            ]
        lines.append("Resume condition: re-run negotiation for this mission after taking the actions above. "
                      "Any requirement that was gapped and is now satisfied will be marked "
                      f"`{DISCOVERED_AFTER_STARTUP}` and the mission re-evaluated -- see check_resume().")
    return "\n".join(lines) + "\n"


def publish_report(result: NegotiationResult, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (REPORTS_DIR / result.mission_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    registry_snapshot = discover.load_registry()
    (out_dir / "CAPABILITY_REGISTRY.json").write_text(json.dumps({"schema_version": 1, "capabilities": registry_snapshot}, indent=2))

    (out_dir / "CAPABILITY_REPORT.json").write_text(json.dumps(result.as_dict(), indent=2))

    (out_dir / "CAPABILITY_GAPS.json").write_text(json.dumps(
        {"mission_id": result.mission_id, "gap_count": len(result.gaps), "gaps": [g.as_dict() for g in result.gaps]},
        indent=2,
    ))

    (out_dir / "OPERATOR_ACTIONS.md").write_text(generate_operator_actions_md(result))

    (out_dir / "CAPABILITY_EVIDENCE.json").write_text(json.dumps(
        {"mission_id": result.mission_id, "generated_at": result.generated_at,
         "evidence": {r.capability_id: {"state": r.state, "evidence": r.evidence} for r in result.requirements}},
        indent=2,
    ))

    history_path = REPORTS_DIR / "negotiation_history.jsonl"
    with history_path.open("a") as f:
        f.write(json.dumps({
            "mission_id": result.mission_id, "generated_at": result.generated_at,
            "can_proceed": result.can_proceed, "gap_count": len(result.gaps),
            "gap_capability_ids": [g.capability_id for g in result.gaps],
        }) + "\n")

    return out_dir


def check_resume(mission_id: str, live_connectors: list[str] | None = None,
                  policy_overrides: dict | None = None, out_dir: Path | None = None) -> dict:
    """Re-runs negotiation and compares against the last published report
    for this mission. Any requirement that was gapped before and is
    satisfied now is reported as DISCOVERED_AFTER_STARTUP. This function
    IS the resume mechanism -- there is no background daemon watching for
    capability changes; re-invoking this (by hand, by a scheduled Routine,
    or by the agent re-checking) is what "automatic" resume means here,
    and that's stated plainly rather than implied to be more than it is.
    """
    out_dir = out_dir or (REPORTS_DIR / mission_id)
    prior_path = out_dir / "CAPABILITY_REPORT.json"
    prior_gap_ids = set()
    if prior_path.exists():
        prior = json.loads(prior_path.read_text())
        prior_gap_ids = {g["capability_id"] for g in prior.get("gaps", [])}

    result = negotiate(mission_id, live_connectors=live_connectors, policy_overrides=policy_overrides)

    newly_resolved = []
    for r in result.requirements:
        if r.capability_id in prior_gap_ids and r.state in SATISFIED_STATES:
            r.state = DISCOVERED_AFTER_STARTUP
            newly_resolved.append(r.capability_id)

    publish_report(result, out_dir=out_dir)

    if not prior_gap_ids:
        overall_status = RESUME_NO_PRIOR_GAP
    elif result.can_proceed:
        overall_status = RESUME_READY
    else:
        overall_status = RESUME_STILL_BLOCKED

    return {
        "mission_id": mission_id,
        "overall_status": overall_status,
        "previously_gapped": sorted(prior_gap_ids),
        "newly_resolved": newly_resolved,
        "still_gapped": [g.capability_id for g in result.gaps],
        "can_proceed_now": result.can_proceed,
        "mission_continuation": "automatic on next negotiation call" if result.can_proceed else "still blocked",
    }
