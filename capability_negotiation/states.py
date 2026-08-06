"""Capability states and gap classifications for the Capability Negotiation
Engine. Every capability a mission depends on ends in exactly one state;
every unmet requirement gets exactly one gap classification with a
specific evidence string -- never a bare "failed"."""

# --- capability states -------------------------------------------------
AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"
BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
DISCOVERED_AFTER_STARTUP = "DISCOVERED_AFTER_STARTUP"
# A deterministic cross-platform mismatch (e.g. this capability only
# exists on Windows and we're on Android/Linux, or vice versa) -- more
# specific than plain UNAVAILABLE because the fix is never "install
# something here," it's "run this step on the right platform."
BLOCKED_BY_PLATFORM = "BLOCKED_BY_PLATFORM"
# Not a gap at all: a mission-level policy decision that this capability
# is intentionally never attempted on this device and is always routed
# to another device instead. See missions.py's delegate_to_windows_ids.
DELEGATE_TO_WINDOWS = "DELEGATE_TO_WINDOWS"

STATES = [
    AVAILABLE, UNAVAILABLE, UNKNOWN, BLOCKED_BY_POLICY, OPERATOR_REQUIRED,
    DISCOVERED_AFTER_STARTUP, BLOCKED_BY_PLATFORM, DELEGATE_TO_WINDOWS,
]

# Mission-level outcome of check_resume() -- distinct from the per-
# capability states above. READY_TO_RESUME describes the WHOLE mission
# ("everything that was gapped is satisfied now"), not one requirement.
RESUME_READY = "READY_TO_RESUME"
RESUME_STILL_BLOCKED = "STILL_BLOCKED"
RESUME_NO_PRIOR_GAP = "NO_PRIOR_GAP"

# States that count as "this requirement is met" for a proceed decision.
# DELEGATE_TO_WINDOWS counts as satisfied *for the mobile side* of a
# mission -- delegating is the intended, complete resolution, not a
# blocker on this device. It does NOT mean the work happened; see
# mission_handoff.py on the mobile-research side for how a delegated
# capability actually gets executed (a Windows-bound handoff package).
SATISFIED_STATES = {AVAILABLE, DISCOVERED_AFTER_STARTUP, DELEGATE_TO_WINDOWS}

# --- gap classifications ------------------------------------------------
GAP_MISSING_CONNECTOR = "missing_connector"
GAP_MISSING_FILESYSTEM_ACCESS = "missing_filesystem_access"
GAP_MISSING_RUNTIME = "missing_runtime"
GAP_MISSING_EXECUTABLE = "missing_executable"
GAP_MISSING_PERMISSION = "missing_permission"
GAP_MISSING_REPOSITORY = "missing_repository"
GAP_MISSING_DEPENDENCY = "missing_dependency"
GAP_MISSING_OPERATOR_AUTHORIZATION = "missing_operator_authorization"

GAP_CLASSES = [
    GAP_MISSING_CONNECTOR, GAP_MISSING_FILESYSTEM_ACCESS, GAP_MISSING_RUNTIME,
    GAP_MISSING_EXECUTABLE, GAP_MISSING_PERMISSION, GAP_MISSING_REPOSITORY,
    GAP_MISSING_DEPENDENCY, GAP_MISSING_OPERATOR_AUTHORIZATION,
]

# check type (from capabilities/registry.json) -> default gap class when
# that check fails. This is a default, not a guarantee -- classify_gap()
# in engine.py can override it with a more specific reading of the evidence.
CHECK_TYPE_TO_DEFAULT_GAP = {
    "command": GAP_MISSING_EXECUTABLE,
    "env": GAP_MISSING_DEPENDENCY,
    "network": GAP_MISSING_CONNECTOR,
    "connector": GAP_MISSING_CONNECTOR,
    "platform": GAP_MISSING_FILESYSTEM_ACCESS,
    "termux": GAP_MISSING_RUNTIME,
    "manual": GAP_MISSING_OPERATOR_AUTHORIZATION,
    "self": None,  # 'self' checks are always AVAILABLE; no gap possible
}
