"""Phone-to-Windows mission handoff contract (structured, not conversational).

A mission package is a self-contained JSON request the Windows ForgeWorld
runtime can act on without reconstructing the request from chat history.
Creating one automatically negotiates each required capability (reusing
capability_negotiation/engine.py -- not duplicating that logic) and buckets
it into mobile_available / windows_required / operator_required, so the
package is honest about what this device can and can't do for itself
before it's ever sent anywhere.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CAP_NEG_DIR = REPO_ROOT / "capability_negotiation"
CAPABILITIES_DIR = REPO_ROOT / "capabilities"

PRIORITIES = ("low", "normal", "high", "urgent")

REQUIRED_FIELDS = [
    "mission_id", "created_on_device", "requested_outcome", "source_records",
    "required_capabilities", "mobile_available", "windows_required",
    "operator_required", "constraints", "evidence", "priority",
    "resource_profile", "resume_condition",
]


def _capability_states(required_capabilities: list[str], live_connectors: list[str] | None = None) -> dict[str, str]:
    """Reuses the Capability Negotiation Engine's probes directly rather
    than re-implementing reachability checks here. Returns {cap_id: state}
    for every requested capability, including ones not in the registry at
    all (state 'UNKNOWN' with a clear reason, never silently dropped)."""
    sys.path.insert(0, str(CAPABILITIES_DIR))
    sys.path.insert(0, str(CAP_NEG_DIR))
    import discover  # noqa: E402

    registry_by_id = {cap["id"]: cap for cap in discover.load_registry()}
    probe = discover.probe_all(live_connectors=live_connectors)

    states = {}
    for cap_id in required_capabilities:
        if cap_id not in registry_by_id:
            states[cap_id] = "UNKNOWN"
            continue
        p = probe.get(cap_id, {})
        confidence = p.get("reachability_confidence", 0.0)
        check_type = registry_by_id[cap_id]["check"].get("type")
        if check_type == "self" or confidence >= 1.0:
            states[cap_id] = "AVAILABLE"
        elif check_type == "platform" and confidence <= 0.0:
            states[cap_id] = "BLOCKED_BY_PLATFORM"
        elif check_type == "connector" and "no live connector list supplied" in p.get("evidence", ""):
            states[cap_id] = "OPERATOR_REQUIRED"
        elif confidence <= 0.0:
            states[cap_id] = "UNAVAILABLE"
        else:
            states[cap_id] = "UNKNOWN"
    return states


def _bucket_capabilities(states: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """mobile_available, windows_required, operator_required -- exactly
    the three buckets the mission package schema has room for.
    UNAVAILABLE defaults to operator_required (something plainly missing
    needs an operator's attention, not an assumption that Windows can
    magically do it); BLOCKED_BY_PLATFORM and DELEGATE_TO_WINDOWS both
    mean "the other platform can do this," so both route to
    windows_required."""
    mobile_available, windows_required, operator_required = [], [], []
    for cap_id, state in states.items():
        if state in ("AVAILABLE", "DISCOVERED_AFTER_STARTUP"):
            mobile_available.append(cap_id)
        elif state in ("BLOCKED_BY_PLATFORM", "DELEGATE_TO_WINDOWS"):
            windows_required.append(cap_id)
        else:  # OPERATOR_REQUIRED, UNKNOWN, BLOCKED_BY_POLICY, UNAVAILABLE
            operator_required.append(cap_id)
    return mobile_available, windows_required, operator_required


def _mission_id(requested_outcome: str, created_on_device: str) -> str:
    digest = hashlib.sha256(f"{requested_outcome}|{created_on_device}".encode()).hexdigest()[:12]
    return f"MH-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{digest}"


def create_mission_package(
    requested_outcome: str,
    source_records: list[dict[str, Any]] | None = None,
    required_capabilities: list[str] | None = None,
    constraints: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    priority: str = "normal",
    resource_profile: str | None = None,
    resume_condition: str | None = None,
    live_connectors: list[str] | None = None,
) -> dict[str, Any]:
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {PRIORITIES}, got {priority!r}")

    created_on_device = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    required_capabilities = required_capabilities or []
    states = _capability_states(required_capabilities, live_connectors=live_connectors)
    mobile_available, windows_required, operator_required = _bucket_capabilities(states)

    package = {
        "mission_id": _mission_id(requested_outcome, created_on_device),
        "created_on_device": created_on_device,
        "requested_outcome": requested_outcome,
        "source_records": source_records or [],
        "required_capabilities": required_capabilities,
        "mobile_available": mobile_available,
        "windows_required": windows_required,
        "operator_required": operator_required,
        "constraints": constraints or [],
        "evidence": evidence or [],
        "priority": priority,
        "resource_profile": resource_profile,
        "resume_condition": resume_condition or "operator or scheduled Routine re-invokes negotiation for the windows_required capabilities above",
        "_capability_states": states,  # full detail, not required by the schema but useful for debugging
    }
    return package


def validate_mission_package(package: dict[str, Any]) -> list[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in package:
            errors.append(f"missing required field '{field}'")
    if "priority" in package and package["priority"] not in PRIORITIES:
        errors.append(f"priority '{package['priority']}' not one of {PRIORITIES}")
    if "mission_id" in package and not str(package["mission_id"]).strip():
        errors.append("mission_id is empty")
    for list_field in ("source_records", "required_capabilities", "mobile_available",
                        "windows_required", "operator_required", "constraints", "evidence"):
        if list_field in package and not isinstance(package[list_field], list):
            errors.append(f"'{list_field}' must be a list")
    return errors


def save_mission_package(package: dict[str, Any], missions_dir: Path) -> Path:
    errors = validate_mission_package(package)
    if errors:
        raise ValueError(f"cannot save invalid mission package: {errors}")
    missions_dir.mkdir(parents=True, exist_ok=True)
    out_path = missions_dir / f"{package['mission_id']}.json"
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(package, indent=2))
    tmp.replace(out_path)
    return out_path


def list_mission_packages(missions_dir: Path) -> list[dict[str, Any]]:
    if not missions_dir.exists():
        return []
    packages = []
    for path in sorted(missions_dir.glob("*.json")):
        try:
            packages.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return packages


def load_mission_package(missions_dir: Path, mission_id: str) -> dict[str, Any] | None:
    path = missions_dir / f"{mission_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
