// Pocket Cortex context integrity check -- the CONTEXT step of the
// governing chain (INTENT -> CONTEXT -> EVIDENCE QUALIFICATION -> MISSION
// -> CAPABILITY CHECK -> AUTHORITY CHECK -> EXECUTION -> VERIFICATION ->
// MEMORY -> NEXT-RIGHT-MOVE).
//
// Small, in-process cousin of scripts/forge_context_gate.py's severity
// vocabulary (PASS / WARNING / CONTEXT_MISMATCH / BLOCKED) -- not a port
// of that script (which checks a filesystem/git/import-graph reality,
// a different domain entirely), but the same discipline applied here:
// verify the request describes something that actually exists in this
// server's own state before acting on it, rather than trusting the
// caller's claim.

import { listCapabilities } from "./governance.js";
import { getMission } from "./db.js";

export const ContextStatus = Object.freeze({
  PASS: "PASS",
  WARNING: "WARNING",
  CONTEXT_MISMATCH: "CONTEXT_MISMATCH",
  BLOCKED: "BLOCKED",
});

export const KNOWN_ROUTE_NODES = Object.freeze([
  "analyze", "discover", "learn", "design", "explain", "execute", "create",
]);

/**
 * Verify a request's claims against actual server state before any
 * downstream stage (capability check, authority check, execution) runs.
 */
export function checkContext(db, { missionId, capability, routeNodes } = {}) {
  const findings = [];
  let status = ContextStatus.PASS;

  function raise(newStatus, note) {
    findings.push(note);
    const rank = { PASS: 0, WARNING: 1, CONTEXT_MISMATCH: 2, BLOCKED: 3 };
    if (rank[newStatus] > rank[status]) status = newStatus;
  }

  if (missionId !== undefined) {
    const mission = getMission(db, missionId);
    if (!mission) {
      raise(ContextStatus.BLOCKED, `mission '${missionId}' does not exist in this server's database -- request describes a reality this server does not have.`);
    } else if (mission.status !== "ACTIVE") {
      raise(ContextStatus.WARNING, `mission '${missionId}' has status '${mission.status}', not ACTIVE.`);
    }
  }

  if (capability !== undefined) {
    const known = listCapabilities();
    if (!known.includes(capability)) {
      raise(ContextStatus.CONTEXT_MISMATCH, `capability '${capability}' is not one this server's policy table (governance.js) defines. Known: ${known.join(", ")}.`);
    }
  }

  if (routeNodes !== undefined) {
    const bad = routeNodes.filter((n) => !KNOWN_ROUTE_NODES.includes(n));
    if (bad.length) {
      raise(ContextStatus.CONTEXT_MISMATCH, `route node(s) not recognized: ${bad.join(", ")}. Known: ${KNOWN_ROUTE_NODES.join(", ")}.`);
    }
  }

  if (!findings.length) findings.push("all claims verified against live server state.");

  return { status, findings, authorizedToContinue: status === ContextStatus.PASS || status === ContextStatus.WARNING };
}
