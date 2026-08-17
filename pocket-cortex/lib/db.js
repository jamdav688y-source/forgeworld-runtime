// Pocket Cortex persistence layer.
//
// Uses node:sqlite (Node's built-in module, stable as of Node 22.5+,
// still flagged experimental by the runtime itself as of this writing --
// that warning is Node's, not a defect here). Deliberately does NOT use
// better-sqlite3 or any other npm dependency: this keeps `npm install`
// out of the Termux deployment path entirely, which matters on a
// resource-constrained phone with a metered/patchy connection. See
// docs/POCKET_CORTEX_ARCHITECTURE.md "Why node:sqlite, not better-sqlite3".
//
// Schema is created with CREATE TABLE IF NOT EXISTS only -- this file
// never DROPs or ALTERs a table. A fresh phone install and a years-old
// database both open through the same code path without migration risk.

import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS missions (
  id TEXT PRIMARY KEY,
  goal_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  stage TEXT NOT NULL DEFAULT 'INTENT',
  route_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_decisions (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(id),
  goal_text TEXT NOT NULL,
  matched_json TEXT NOT NULL,
  scores_json TEXT NOT NULL,
  rationale TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_records (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(id),
  subject TEXT NOT NULL,
  state TEXT NOT NULL,
  observation TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_attempts (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(id),
  capability TEXT NOT NULL,
  authority_decision TEXT NOT NULL,
  outcome TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS next_moves (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(id),
  move_text TEXT NOT NULL,
  basis TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_routing_mission ON routing_decisions(mission_id);
CREATE INDEX IF NOT EXISTS idx_evidence_mission ON evidence_records(mission_id);
CREATE INDEX IF NOT EXISTS idx_execution_mission ON execution_attempts(mission_id);
CREATE INDEX IF NOT EXISTS idx_nextmove_mission ON next_moves(mission_id);
`;

export function openDatabase(path) {
  if (path !== ":memory:") {
    mkdirSync(dirname(path), { recursive: true });
  }
  const db = new DatabaseSync(path);
  db.exec("PRAGMA journal_mode = WAL;");
  db.exec("PRAGMA foreign_keys = ON;");
  db.exec(SCHEMA);
  return db;
}

function nowIso() {
  return new Date().toISOString();
}

function newId(prefix) {
  return `${prefix}-${randomUUID().slice(0, 8)}`;
}

export function createMission(db, goalText) {
  const id = newId("MSN");
  const ts = nowIso();
  db.prepare(
    `INSERT INTO missions (id, goal_text, status, stage, route_json, created_at, updated_at)
     VALUES (?, ?, 'ACTIVE', 'INTENT', '[]', ?, ?)`
  ).run(id, goalText, ts, ts);
  return getMission(db, id);
}

export function getMission(db, id) {
  const row = db.prepare("SELECT * FROM missions WHERE id = ?").get(id);
  if (!row) return null;
  return { ...row, route: JSON.parse(row.route_json) };
}

export function listMissions(db, { limit = 50 } = {}) {
  const rows = db
    .prepare("SELECT * FROM missions ORDER BY updated_at DESC LIMIT ?")
    .all(limit);
  return rows.map((row) => ({ ...row, route: JSON.parse(row.route_json) }));
}

export function updateMissionGoal(db, id, goalText) {
  const ts = nowIso();
  db.prepare("UPDATE missions SET goal_text = ?, updated_at = ? WHERE id = ?").run(goalText, ts, id);
  return getMission(db, id);
}

export function updateMissionRoute(db, id, { stage, route }) {
  const ts = nowIso();
  db.prepare(
    "UPDATE missions SET stage = ?, route_json = ?, updated_at = ? WHERE id = ?"
  ).run(stage, JSON.stringify(route), ts, id);
  return getMission(db, id);
}

export function recordRoutingDecision(db, missionId, { goalText, matched, scores, rationale }) {
  const id = newId("RTE");
  const ts = nowIso();
  db.prepare(
    `INSERT INTO routing_decisions (id, mission_id, goal_text, matched_json, scores_json, rationale, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(id, missionId, goalText, JSON.stringify(matched), JSON.stringify(scores), rationale, ts);
  return { id, missionId, goalText, matched, scores, rationale, createdAt: ts };
}

export function getRoutingHistory(db, missionId) {
  const rows = db
    .prepare("SELECT * FROM routing_decisions WHERE mission_id = ? ORDER BY created_at ASC")
    .all(missionId);
  return rows.map((r) => ({
    id: r.id,
    goalText: r.goal_text,
    matched: JSON.parse(r.matched_json),
    scores: JSON.parse(r.scores_json),
    rationale: r.rationale,
    createdAt: r.created_at,
  }));
}

export function recordEvidence(db, missionId, { subject, state, observation, source }) {
  const id = newId("EVD");
  const ts = nowIso();
  db.prepare(
    `INSERT INTO evidence_records (id, mission_id, subject, state, observation, source, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(id, missionId, subject, state, observation, source, ts);
  return { id, missionId, subject, state, observation, source, createdAt: ts };
}

export function getEvidence(db, missionId) {
  const rows = db
    .prepare("SELECT * FROM evidence_records WHERE mission_id = ? ORDER BY created_at ASC")
    .all(missionId);
  return rows.map((r) => ({
    id: r.id,
    subject: r.subject,
    state: r.state,
    observation: r.observation,
    source: r.source,
    createdAt: r.created_at,
  }));
}

export function recordExecutionAttempt(db, missionId, { capability, authorityDecision, outcome, detail = "" }) {
  const id = newId("EXE");
  const ts = nowIso();
  db.prepare(
    `INSERT INTO execution_attempts (id, mission_id, capability, authority_decision, outcome, detail, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(id, missionId, capability, authorityDecision, outcome, detail, ts);
  return { id, missionId, capability, authorityDecision, outcome, detail, createdAt: ts };
}

export function getExecutionAttempts(db, missionId) {
  const rows = db
    .prepare("SELECT * FROM execution_attempts WHERE mission_id = ? ORDER BY created_at ASC")
    .all(missionId);
  return rows.map((r) => ({
    id: r.id,
    capability: r.capability,
    authorityDecision: r.authority_decision,
    outcome: r.outcome,
    detail: r.detail,
    createdAt: r.created_at,
  }));
}

export function recordNextMove(db, missionId, { text, basis }) {
  const id = newId("NXT");
  const ts = nowIso();
  db.prepare(
    `INSERT INTO next_moves (id, mission_id, move_text, basis, created_at)
     VALUES (?, ?, ?, ?, ?)`
  ).run(id, missionId, text, basis, ts);
  return { id, missionId, text, basis, createdAt: ts };
}

export function getCurrentNextMove(db, missionId) {
  // Tiebreak on rowid (SQLite's own monotonic insertion-order column,
  // present implicitly on any ordinary table) in addition to created_at:
  // two next_moves recorded within the same millisecond would otherwise
  // have an unstable/arbitrary relative order under created_at alone,
  // and this function must always return the ACTUAL most recent one, not
  // an arbitrary tied one.
  const row = db
    .prepare("SELECT * FROM next_moves WHERE mission_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1")
    .get(missionId);
  if (!row) return null;
  return { id: row.id, text: row.move_text, basis: row.basis, createdAt: row.created_at };
}

export function getMissionFull(db, id) {
  const mission = getMission(db, id);
  if (!mission) return null;
  return {
    mission,
    routing: getRoutingHistory(db, id),
    evidence: getEvidence(db, id),
    execution: getExecutionAttempts(db, id),
    nextMove: getCurrentNextMove(db, id),
  };
}
