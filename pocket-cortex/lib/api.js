// API handlers -- pure functions of (db, repoRoot, input) -> { status, body }
// so they can be unit-tested directly without spinning up an HTTP server.
// server.js is only responsible for parsing requests into `input` and
// writing `{status, body}` back out as JSON.
//
// Every handler that mutates or executes something walks the same
// governing chain the mission specifies:
//   CONTEXT check -> CAPABILITY check -> AUTHORITY check -> EXECUTION
//   -> record EVIDENCE/EXECUTION -> recompute NEXT-RIGHT-MOVE
// No handler skips a stage because an earlier one passed.

import { execFileSync } from "node:child_process";
import * as db from "./db.js";
import { routeIntent } from "./routing.js";
import { computeIndicators } from "./indicators.js";
import { generateNextMove } from "./nextMove.js";
import { checkContext } from "./context.js";
import { evaluateAuthority, listCapabilities, isAutonomouslyExecutable } from "./governance.js";
import { checkCapability } from "./capability.js";

// Process-lifetime rate-limit state for bounded capabilities. Reset on
// restart by design -- there is no need for this to survive a restart,
// and persisting it would just be one more piece of state to reason
// about for no behavioral benefit.
const lastRunAt = new Map();

function missionSnapshot(conn, missionId) {
  const full = db.getMissionFull(conn, missionId);
  if (!full) return null;
  const indicators = computeIndicators({
    routingHistory: full.routing,
    evidenceRecords: full.evidence,
    executionAttempts: full.execution,
  });
  const nextMove = generateNextMove({
    mission: full.mission,
    routingHistory: full.routing,
    evidenceRecords: full.evidence,
    executionAttempts: full.execution,
  });
  return { ...full, indicators, nextMove };
}

export function createMissionHandler(conn, repoRoot, { goalText }) {
  if (typeof goalText !== "string" || !goalText.trim()) {
    return { status: 400, body: { error: "goalText is required" } };
  }
  const capability = checkCapability("CREATE_MISSION", repoRoot);
  const authority = evaluateAuthority("CREATE_MISSION");
  if (!capability.available || !isAutonomouslyExecutable(authority.decision)) {
    return { status: 403, body: { error: "CREATE_MISSION not available", capability, authority } };
  }

  const mission = db.createMission(conn, goalText.trim());
  const { matched, scores, rationale } = routeIntent(goalText.trim());
  db.recordRoutingDecision(conn, mission.id, { goalText: goalText.trim(), matched, scores, rationale });
  db.updateMissionRoute(conn, mission.id, { stage: matched.length ? "ROUTE" : "INTENT", route: matched });
  db.recordExecutionAttempt(conn, mission.id, { capability: "CREATE_MISSION", authorityDecision: authority.decision, outcome: "SUCCEEDED" });

  return { status: 201, body: missionSnapshot(conn, mission.id) };
}

export function listMissionsHandler(conn) {
  return { status: 200, body: { missions: db.listMissions(conn) } };
}

export function getMissionHandler(conn, missionId) {
  const context = checkContext(conn, { missionId });
  if (!context.authorizedToContinue) {
    return { status: 404, body: { error: "mission not found", context } };
  }
  return { status: 200, body: missionSnapshot(conn, missionId) };
}

export function rerouteMissionHandler(conn, repoRoot, missionId, { goalText }) {
  const context = checkContext(conn, { missionId });
  if (!context.authorizedToContinue) {
    return { status: 404, body: { error: "mission not found", context } };
  }
  if (typeof goalText !== "string" || !goalText.trim()) {
    return { status: 400, body: { error: "goalText is required" } };
  }
  const authority = evaluateAuthority("UPDATE_ROUTE");
  if (!isAutonomouslyExecutable(authority.decision)) {
    return { status: 403, body: { error: "UPDATE_ROUTE not authorized", authority } };
  }

  db.updateMissionGoal(conn, missionId, goalText.trim());
  const { matched, scores, rationale } = routeIntent(goalText.trim());
  db.recordRoutingDecision(conn, missionId, { goalText: goalText.trim(), matched, scores, rationale });
  db.updateMissionRoute(conn, missionId, { stage: "ROUTE", route: matched });

  return { status: 200, body: missionSnapshot(conn, missionId) };
}

export function recordEvidenceHandler(conn, missionId, { subject, state, observation, source }) {
  const context = checkContext(conn, { missionId });
  if (!context.authorizedToContinue) {
    return { status: 404, body: { error: "mission not found", context } };
  }
  const validStates = ["UNKNOWN", "OBSERVED", "SUPPORTED", "VALIDATED", "INSTITUTIONALIZED"];
  if (!validStates.includes(state)) {
    return { status: 400, body: { error: `state must be one of ${validStates.join(", ")}` } };
  }
  if (typeof subject !== "string" || !subject.trim() || typeof observation !== "string" || !observation.trim()) {
    return { status: 400, body: { error: "subject and observation are required" } };
  }
  const authority = evaluateAuthority("RECORD_EVIDENCE");
  db.recordEvidence(conn, missionId, {
    subject: subject.trim(),
    state,
    observation: observation.trim(),
    source: source && source.trim() ? source.trim() : "user",
  });
  db.recordExecutionAttempt(conn, missionId, { capability: "RECORD_EVIDENCE", authorityDecision: authority.decision, outcome: "SUCCEEDED" });
  return { status: 201, body: missionSnapshot(conn, missionId) };
}

export function advanceStageHandler(conn, missionId, { stage }) {
  const context = checkContext(conn, { missionId });
  if (!context.authorizedToContinue) {
    return { status: 404, body: { error: "mission not found", context } };
  }
  const validStages = ["INTENT", "ROUTE", "WORK", "REVIEW", "NEXT"];
  if (!validStages.includes(stage)) {
    return { status: 400, body: { error: `stage must be one of ${validStages.join(", ")}` } };
  }
  const mission = db.getMission(conn, missionId);
  db.updateMissionRoute(conn, missionId, { stage, route: mission.route });
  return { status: 200, body: missionSnapshot(conn, missionId) };
}

export function listCapabilitiesHandler(conn, repoRoot) {
  const entries = listCapabilities().map((name) => {
    const authority = evaluateAuthority(name, { lastRunAt: lastRunAt.get(name) });
    const capability = checkCapability(name, repoRoot);
    return { name, capability, authority };
  });
  return { status: 200, body: { capabilities: entries } };
}

/**
 * The one handler in this file that can perform a REAL side-effecting
 * action (shelling out to forge_reconcile.py, which is itself read-only
 * by its own contract -- see scripts/forge_reconcile.py's docstring).
 * Everything else here only ever touches this server's own sqlite file.
 */
export function executeCapabilityHandler(conn, repoRoot, missionId, { capability }) {
  const context = checkContext(conn, { missionId, capability });
  if (!context.authorizedToContinue) {
    return { status: 404, body: { error: "context check failed", context } };
  }

  const capCheck = checkCapability(capability, repoRoot);
  if (!capCheck.available) {
    db.recordExecutionAttempt(conn, missionId, { capability, authorityDecision: "UNAVAILABLE", outcome: "BLOCKED", detail: capCheck.evidence });
    return { status: 409, body: { error: "capability unavailable", capability: capCheck, snapshot: missionSnapshot(conn, missionId) } };
  }

  const authority = evaluateAuthority(capability, { lastRunAt: lastRunAt.get(capability) });

  if (authority.decision === "REQUIRES_APPROVAL") {
    db.recordExecutionAttempt(conn, missionId, { capability, authorityDecision: authority.decision, outcome: "AWAITING_APPROVAL", detail: authority.reason });
    return { status: 202, body: { authority, snapshot: missionSnapshot(conn, missionId) } };
  }

  if (!isAutonomouslyExecutable(authority.decision)) {
    db.recordExecutionAttempt(conn, missionId, { capability, authorityDecision: authority.decision, outcome: "BLOCKED", detail: authority.reason });
    return { status: 403, body: { error: "not authorized", authority, snapshot: missionSnapshot(conn, missionId) } };
  }

  // ALLOWED / ALLOWED_LOCAL / ALLOWED_BOUNDED from here down.
  if (capability === "RUN_RECONCILE_SCAN") {
    lastRunAt.set(capability, Date.now());
    try {
      const out = execFileSync(
        "python3",
        ["scripts/forge_reconcile.py", "--no-fetch", "--root", repoRoot, "--out", `${repoRoot}/pocket-cortex/data/reconcile-output`],
        { cwd: repoRoot, encoding: "utf8", timeout: 30_000 }
      );
      db.recordExecutionAttempt(conn, missionId, { capability, authorityDecision: authority.decision, outcome: "SUCCEEDED", detail: out.slice(-2000) });
      db.recordEvidence(conn, missionId, { subject: "reconcile-scan", state: "OBSERVED", observation: out.slice(-500), source: "forge_reconcile.py" });
    } catch (err) {
      db.recordExecutionAttempt(conn, missionId, { capability, authorityDecision: authority.decision, outcome: "FAILED", detail: String(err.message || err).slice(0, 2000) });
      return { status: 500, body: { error: "reconcile scan failed", snapshot: missionSnapshot(conn, missionId) } };
    }
    return { status: 200, body: missionSnapshot(conn, missionId) };
  }

  // Generic capabilities with no further side effect beyond the record itself.
  db.recordExecutionAttempt(conn, missionId, { capability, authorityDecision: authority.decision, outcome: "SUCCEEDED" });
  return { status: 200, body: missionSnapshot(conn, missionId) };
}
