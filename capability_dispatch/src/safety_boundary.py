"""THIRD-PARTY SAFETY BOUNDARY (mission Section 13).

No function anywhere in this package installs, clones, executes, or
grants authority to a third-party candidate -- this is a structural claim,
verifiable by grep: nothing in capability_dispatch/src/ imports
subprocess, os.system, shutil.copytree-from-a-clone, git-clone tooling, or
any package-manager invocation. capability_dispatch/tests/test_safety_boundary.py
asserts this by source inspection, not just by convention.

The 13 pre-installation requirements are modeled here as an explicit,
checkable data structure -- PRE_INSTALLATION_GATES -- rather than left as
prose a future change could quietly forget. installation_authorized()
requires every single gate to be explicitly satisfied; there is no partial
threshold, no majority vote, and no bypass parameter. This mission
supplies satisfied=False for every gate on every candidate (no
installation authority was granted), so installation_authorized() can
never return True from anything this mission itself produced -- verified
in test_safety_boundary.py.
"""

PRE_INSTALLATION_GATES = [
    "verified_canonical_identity",
    "license_review",
    "maintainer_and_maintenance_review",
    "dependency_inspection",
    "install_script_inspection",
    "execution_surface_classification",
    "credential_surface_classification",
    "network_surface_classification",
    "filesystem_and_shell_analysis",
    "overlap_analysis",
    "isolated_sandbox_benchmark",
    "evidence_sufficiency_decision",
    "explicit_installation_authority",
]


def new_gate_checklist() -> dict:
    """Every gate defaults to False -- satisfied only by an explicit,
    separately-evidenced call, never assumed."""
    return {gate: False for gate in PRE_INSTALLATION_GATES}


def installation_authorized(checklist: dict) -> bool:
    """True only if every single gate in PRE_INSTALLATION_GATES is present
    and True in `checklist`. A missing key is treated as not satisfied,
    never as satisfied-by-omission."""
    return all(checklist.get(gate) is True for gate in PRE_INSTALLATION_GATES)


def unsatisfied_gates(checklist: dict) -> list:
    return [gate for gate in PRE_INSTALLATION_GATES if checklist.get(gate) is not True]
