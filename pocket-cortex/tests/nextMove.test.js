import { test } from "node:test";
import assert from "node:assert/strict";
import { generateNextMove } from "../lib/nextMove.js";

test("unresolved AWAITING_APPROVAL execution outranks everything else", () => {
  const move = generateNextMove({
    mission: { route: ["execute"], stage: "WORK" },
    routingHistory: [{}],
    evidenceRecords: [{ state: "VALIDATED" }],
    executionAttempts: [{ id: "EXE-1", capability: "TRIGGER_PHONE_DEPLOY", outcome: "AWAITING_APPROVAL" }],
  });
  assert.match(move.text, /Resolve the pending TRIGGER_PHONE_DEPLOY approval/);
});

test("no route matched -> tells the user to rephrase, not a generic platitude", () => {
  const move = generateNextMove({
    mission: { route: [], stage: "INTENT" },
    routingHistory: [{}],
    evidenceRecords: [],
    executionAttempts: [],
  });
  assert.match(move.text, /Rephrase the goal/);
});

test("route matched but no evidence -> asks for confirmation, names UNKNOWN -> OBSERVED", () => {
  const move = generateNextMove({
    mission: { route: ["learn"], stage: "ROUTE" },
    routingHistory: [{}],
    evidenceRecords: [],
    executionAttempts: [],
  });
  assert.match(move.text, /Confirm whether the current route/);
  assert.match(move.text, /OBSERVED/);
});

test("single OBSERVED evidence record with only one routing pass -> asks for corroboration", () => {
  const move = generateNextMove({
    mission: { route: ["learn"], stage: "ROUTE" },
    routingHistory: [{}],
    evidenceRecords: [{ state: "OBSERVED" }],
    executionAttempts: [],
  });
  assert.match(move.text, /Restate the goal/);
  assert.match(move.text, /SUPPORTED/);
});

test("stage INTENT with a matched route -> tells you to move to ROUTE", () => {
  const move = generateNextMove({
    mission: { route: ["create"], stage: "INTENT" },
    routingHistory: [{}, {}],
    evidenceRecords: [{ state: "SUPPORTED" }],
    executionAttempts: [],
  });
  assert.match(move.text, /Move this mission into ROUTE/);
});

test("stage WORK with strong evidence but zero execution attempts -> asks for a concrete attempt", () => {
  const move = generateNextMove({
    mission: { route: ["create"], stage: "WORK" },
    routingHistory: [{}, {}],
    evidenceRecords: [{ state: "SUPPORTED" }],
    executionAttempts: [],
  });
  assert.match(move.text, /Record a concrete execution attempt/);
});

test("stage REVIEW -> asks for an explicit decision", () => {
  const move = generateNextMove({
    mission: { route: ["create"], stage: "REVIEW" },
    routingHistory: [{}, {}],
    evidenceRecords: [{ state: "VALIDATED" }],
    executionAttempts: [{ outcome: "SUCCEEDED" }],
  });
  assert.match(move.text, /Decide: is this mission ready/);
});

test("stage NEXT (terminal) -> tells the user the cycle is complete", () => {
  const move = generateNextMove({
    mission: { route: ["create"], stage: "NEXT" },
    routingHistory: [{}, {}],
    evidenceRecords: [{ state: "VALIDATED" }],
    executionAttempts: [{ outcome: "SUCCEEDED" }],
  });
  assert.match(move.text, /active cycle is complete/);
});

test("every generated move includes a basis grounded in actual input, not a static string", () => {
  const move = generateNextMove({
    mission: { route: ["learn"], stage: "ROUTE" },
    routingHistory: [{}],
    evidenceRecords: [],
    executionAttempts: [],
  });
  assert.ok(move.basis.includes("learn"));
});
