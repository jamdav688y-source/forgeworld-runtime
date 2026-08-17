import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as db from "../lib/db.js";

function freshDb() {
  return db.openDatabase(":memory:");
}

test("createMission creates a mission with INTENT stage and empty route", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "Learn something new");
  assert.equal(m.goal_text, "Learn something new");
  assert.equal(m.stage, "INTENT");
  assert.deepEqual(m.route, []);
  assert.equal(m.status, "ACTIVE");
});

test("getMission returns null for unknown id", () => {
  const conn = freshDb();
  assert.equal(db.getMission(conn, "MSN-doesnotexist"), null);
});

test("updateMissionRoute persists stage and route", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  const updated = db.updateMissionRoute(conn, m.id, { stage: "ROUTE", route: ["learn", "explain"] });
  assert.equal(updated.stage, "ROUTE");
  assert.deepEqual(updated.route, ["learn", "explain"]);
  // survives a fresh read, not just the returned object
  assert.deepEqual(db.getMission(conn, m.id).route, ["learn", "explain"]);
});

test("updateMissionGoal changes goal_text without touching route/stage", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "original");
  db.updateMissionRoute(conn, m.id, { stage: "ROUTE", route: ["create"] });
  const updated = db.updateMissionGoal(conn, m.id, "revised");
  assert.equal(updated.goal_text, "revised");
  assert.equal(updated.stage, "ROUTE");
  assert.deepEqual(updated.route, ["create"]);
});

test("listMissions orders by most recently updated first", () => {
  const conn = freshDb();
  const a = db.createMission(conn, "first");
  const b = db.createMission(conn, "second");
  db.updateMissionGoal(conn, a.id, "first, touched again");
  const list = db.listMissions(conn);
  assert.equal(list[0].id, a.id);
  assert.equal(list[1].id, b.id);
});

test("listMissions respects limit", () => {
  const conn = freshDb();
  for (let i = 0; i < 5; i++) db.createMission(conn, `goal ${i}`);
  assert.equal(db.listMissions(conn, { limit: 2 }).length, 2);
});

test("routing decisions round-trip matched/scores as real arrays/objects, not strings", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  db.recordRoutingDecision(conn, m.id, { goalText: "goal", matched: ["learn"], scores: { learn: 2 }, rationale: "because" });
  const history = db.getRoutingHistory(conn, m.id);
  assert.equal(history.length, 1);
  assert.deepEqual(history[0].matched, ["learn"]);
  assert.deepEqual(history[0].scores, { learn: 2 });
  assert.equal(history[0].rationale, "because");
});

test("evidence records round-trip in insertion order", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  db.recordEvidence(conn, m.id, { subject: "a", state: "OBSERVED", observation: "obs1", source: "user" });
  db.recordEvidence(conn, m.id, { subject: "b", state: "SUPPORTED", observation: "obs2", source: "system" });
  const records = db.getEvidence(conn, m.id);
  assert.equal(records.length, 2);
  assert.equal(records[0].subject, "a");
  assert.equal(records[1].state, "SUPPORTED");
});

test("execution attempts round-trip with authority decision and outcome", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  db.recordExecutionAttempt(conn, m.id, { capability: "RUN_RECONCILE_SCAN", authorityDecision: "ALLOWED_BOUNDED", outcome: "SUCCEEDED", detail: "ok" });
  const attempts = db.getExecutionAttempts(conn, m.id);
  assert.equal(attempts.length, 1);
  assert.equal(attempts[0].capability, "RUN_RECONCILE_SCAN");
  assert.equal(attempts[0].outcome, "SUCCEEDED");
});

test("next moves: getCurrentNextMove returns the most recent one", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  db.recordNextMove(conn, m.id, { text: "first move", basis: "b1" });
  db.recordNextMove(conn, m.id, { text: "second move", basis: "b2" });
  const current = db.getCurrentNextMove(conn, m.id);
  assert.equal(current.text, "second move");
});

test("getMissionFull assembles mission + routing + evidence + execution + nextMove", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  db.recordRoutingDecision(conn, m.id, { goalText: "goal", matched: ["create"], scores: { create: 1 }, rationale: "r" });
  db.recordEvidence(conn, m.id, { subject: "s", state: "OBSERVED", observation: "o", source: "user" });
  db.recordExecutionAttempt(conn, m.id, { capability: "CREATE_MISSION", authorityDecision: "ALLOWED", outcome: "SUCCEEDED" });
  db.recordNextMove(conn, m.id, { text: "do X", basis: "because Y" });

  const full = db.getMissionFull(conn, m.id);
  assert.equal(full.mission.id, m.id);
  assert.equal(full.routing.length, 1);
  assert.equal(full.evidence.length, 1);
  assert.equal(full.execution.length, 1);
  assert.equal(full.nextMove.text, "do X");
});

test("getMissionFull returns null for a mission that does not exist", () => {
  const conn = freshDb();
  assert.equal(db.getMissionFull(conn, "MSN-nope"), null);
});

test("schema is safe to re-apply to the same file (CREATE TABLE IF NOT EXISTS, no migration risk)", () => {
  const dir = mkdtempSync(join(tmpdir(), "pocket-cortex-test-"));
  const dbPath = join(dir, "reopen-test.db");
  try {
    const conn1 = db.openDatabase(dbPath);
    const m = db.createMission(conn1, "persisted across reopen");
    conn1.close();

    // Re-opening the SAME file re-runs the full CREATE TABLE IF NOT EXISTS
    // schema against a database that already has data -- must not throw,
    // and the earlier data must still be there afterward.
    const conn2 = db.openDatabase(dbPath);
    assert.equal(db.getMission(conn2, m.id).goal_text, "persisted across reopen");
    conn2.close();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
