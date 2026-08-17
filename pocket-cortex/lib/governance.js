// Pocket Cortex capability/authority model.
//
// Mirrors the vocabulary already established in governance/types.py and
// governance/authority.py (branch claude/forgeworld-authority-separation,
// not yet merged to main) rather than inventing a competing one:
//
//   CAPABILITY != AUTHORITY != EVIDENCE != PROMOTION
//
// Honest limitation, stated up front: the Python governance/ module
// models MULTIPLE actors (human vs. agent) and enforces decider identity
// server-side across a network boundary. Pocket Cortex is a single-user,
// single-device local tool -- there is no second party to check an
// actor's identity against. "Authority" here therefore means something
// narrower and it is important not to overclaim the analogy: a REQUIRES
// _APPROVAL decision in this module is enforced as a mandatory, explicit,
// non-bypassable UI confirmation step (see apiRoutes' handling of
// approvalToken), not as cryptographic proof of who clicked it. It still
// achieves the thing that actually matters for this incident's lesson --
// capability (the server process CAN run forge_deploy.py) is never
// silently treated as authority (permission to run it right now) -- but
// it does so through interaction friction, not identity verification.

export const AuthorityState = Object.freeze({
  DENIED: "DENIED",
  ALLOWED: "ALLOWED",
  ALLOWED_LOCAL: "ALLOWED_LOCAL",
  ALLOWED_BOUNDED: "ALLOWED_BOUNDED",
  REQUIRES_APPROVAL: "REQUIRES_APPROVAL",
  HUMAN_ONLY: "HUMAN_ONLY",
  UNAVAILABLE: "UNAVAILABLE",
  UNKNOWN: "UNKNOWN",
});

// States in which the API may act without a separate confirmation step.
const AUTONOMOUS_STATES = new Set([
  AuthorityState.ALLOWED,
  AuthorityState.ALLOWED_LOCAL,
  AuthorityState.ALLOWED_BOUNDED,
]);

export const EvidenceState = Object.freeze({
  UNKNOWN: "UNKNOWN",
  OBSERVED: "OBSERVED",
  SUPPORTED: "SUPPORTED",
  VALIDATED: "VALIDATED",
  INSTITUTIONALIZED: "INSTITUTIONALIZED",
});

const EVIDENCE_ORDER = [
  EvidenceState.UNKNOWN,
  EvidenceState.OBSERVED,
  EvidenceState.SUPPORTED,
  EvidenceState.VALIDATED,
  EvidenceState.INSTITUTIONALIZED,
];

export function evidenceAtLeast(state, minimum) {
  return EVIDENCE_ORDER.indexOf(state) >= EVIDENCE_ORDER.indexOf(minimum);
}

// Capability policy table. Deliberately small and specific to what this
// server can actually do -- no capability is listed here "for symmetry"
// with the Python table if Pocket Cortex has no code path that performs
// it. Static (not stored in the database, not editable through any API
// route) -- this IS the self-escalation guard: there is no way to reach
// this table from a network request, only from a code change and a
// restart, which is a human action by construction.
const POLICY = Object.freeze({
  CREATE_MISSION: { decision: AuthorityState.ALLOWED, reason: "Creating a local, on-device mission record has no external effect." },
  UPDATE_ROUTE: { decision: AuthorityState.ALLOWED, reason: "Updating a mission's own routing state is local and reversible." },
  RECORD_EVIDENCE: { decision: AuthorityState.ALLOWED, reason: "Recording an observation does not itself change anything else." },
  RECORD_EXECUTION_ATTEMPT: { decision: AuthorityState.ALLOWED, reason: "Logging an attempted action is local bookkeeping." },
  EXPORT_MISSION_DATA: { decision: AuthorityState.ALLOWED_LOCAL, reason: "Export produces a local file download only; it never transmits anything over the network from this server." },
  RUN_RECONCILE_SCAN: {
    decision: AuthorityState.ALLOWED_BOUNDED,
    reason: "forge_reconcile.py is read-only by its own contract, but is bounded here to limit how often a resource-constrained phone re-scans its own filesystem.",
    constraints: { min_seconds_between_runs: 60 },
  },
  TRIGGER_PHONE_DEPLOY: {
    decision: AuthorityState.REQUIRES_APPROVAL,
    reason: "Deploying to the live phone installation is exactly the class of action the NRM tag-push incident showed must never be autonomous. Requires an explicit, single-use approval token from the UI's confirmation step.",
  },
  MODIFY_CAPABILITY_POLICY: {
    decision: AuthorityState.HUMAN_ONLY,
    reason: "Changing this policy table requires editing this source file and restarting the process -- there is no API route that can reach it.",
  },
});

/**
 * The only function allowed to answer "may this happen right now?".
 * Never returns ALLOWED for a capability not in POLICY -- returns
 * UNKNOWN, matching governance/authority.py's evaluate_authority()
 * contract: UNKNOWN must never silently degrade to ALLOWED.
 */
export function evaluateAuthority(capability, context = {}) {
  const entry = POLICY[capability];
  if (!entry) {
    return {
      capability,
      decision: AuthorityState.UNKNOWN,
      reason: `No policy defines capability '${capability}'. Absence of a rule is not permission.`,
      constraints: {},
      approvalRequired: false,
    };
  }

  if (entry.decision === AuthorityState.ALLOWED_BOUNDED && entry.constraints) {
    const { min_seconds_between_runs } = entry.constraints;
    if (min_seconds_between_runs != null) {
      const lastRunAt = context.lastRunAt;
      // No prior run is unambiguous evidence the "minimum time since last
      // run" constraint is satisfied (an unbounded amount of time has
      // elapsed since a run that never happened) -- this is different from
      // a constraint like WRITE_BRANCH's force_push flag, where a missing
      // value is genuinely ambiguous. Do not conflate "no baseline exists
      // yet" with "cannot verify"; only fall back to UNKNOWN for
      // constraint shapes that have no principled default (see the `else`
      // branch below, kept for exactly that case).
      const elapsed = lastRunAt == null ? Infinity : (Date.now() - lastRunAt) / 1000;
      if (elapsed < min_seconds_between_runs) {
        return {
          capability,
          decision: AuthorityState.DENIED,
          reason: `Bounded constraint violated: ran ${elapsed.toFixed(1)}s ago, minimum is ${min_seconds_between_runs}s.`,
          constraints: entry.constraints,
          approvalRequired: false,
        };
      }
    }
  }

  return {
    capability,
    decision: entry.decision,
    reason: entry.reason,
    constraints: entry.constraints || {},
    approvalRequired: entry.decision === AuthorityState.REQUIRES_APPROVAL,
  };
}

export function isAutonomouslyExecutable(decision) {
  return AUTONOMOUS_STATES.has(decision);
}

export function listCapabilities() {
  return Object.keys(POLICY);
}
