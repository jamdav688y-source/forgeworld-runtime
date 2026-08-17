import { test } from "node:test";
import assert from "node:assert/strict";
import * as db from "../lib/db.js";
import { checkContext, ContextStatus } from "../lib/context.js";

function freshDb() {
  return db.openDatabase(":memory:");
}

test("context PASSes for a real mission and a real capability", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  const result = checkContext(conn, { missionId: m.id, capability: "CREATE_MISSION" });
  assert.equal(result.status, ContextStatus.PASS);
  assert.equal(result.authorizedToContinue, true);
});

test("context is BLOCKED for a mission id that does not exist -- this is the whole point of the check", () => {
  const conn = freshDb();
  const result = checkContext(conn, { missionId: "MSN-fabricated" });
  assert.equal(result.status, ContextStatus.BLOCKED);
  assert.equal(result.authorizedToContinue, false);
  assert.match(result.findings[0], /does not exist in this server's database/);
});

test("context is CONTEXT_MISMATCH for a capability not in the policy table", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  const result = checkContext(conn, { missionId: m.id, capability: "NOT_A_REAL_CAPABILITY" });
  assert.equal(result.status, ContextStatus.CONTEXT_MISMATCH);
  assert.equal(result.authorizedToContinue, false);
});

test("context is CONTEXT_MISMATCH for an unrecognized route node", () => {
  const conn = freshDb();
  const result = checkContext(conn, { routeNodes: ["learn", "not-a-real-node"] });
  assert.equal(result.status, ContextStatus.CONTEXT_MISMATCH);
});

test("WARNING (not BLOCKED) for a mission that exists but is not ACTIVE -- degraded, not denied", () => {
  const conn = freshDb();
  const m = db.createMission(conn, "goal");
  conn.prepare("UPDATE missions SET status = 'ARCHIVED' WHERE id = ?").run(m.id);
  const result = checkContext(conn, { missionId: m.id });
  assert.equal(result.status, ContextStatus.WARNING);
  assert.equal(result.authorizedToContinue, true, "WARNING still allows continuation, unlike BLOCKED");
});

test("severity combines correctly: BLOCKED always wins over WARNING/CONTEXT_MISMATCH", () => {
  const conn = freshDb();
  const result = checkContext(conn, { missionId: "MSN-fabricated", capability: "NOT_REAL" });
  assert.equal(result.status, ContextStatus.BLOCKED);
});

test("no claims supplied at all -> PASS with a note, not an error", () => {
  const conn = freshDb();
  const result = checkContext(conn, {});
  assert.equal(result.status, ContextStatus.PASS);
});
