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

STATES = [
    AVAILABLE, UNAVAILABLE, UNKNOWN,
    BLOCKED_BY_POLICY, OPERATOR_REQUIRED, DISCOVERED_AFTER_STARTUP,
]

# States that count as "this requirement is met" for a proceed decision.
SATISFIED_STATES = {AVAILABLE, DISCOVERED_AFTER_STARTUP}

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
    "manual": GAP_MISSING_OPERATOR_AUTHORIZATION,
    "self": None,  # 'self' checks are always AVAILABLE; no gap possible
}
