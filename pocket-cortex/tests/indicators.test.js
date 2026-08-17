import { test } from "node:test";
import assert from "node:assert/strict";
import { computeIndicators } from "../lib/indicators.js";

test("a mission with no data at all reports all-zero indicators, never fabricated optimism", () => {
  const indicators = computeIndicators({ routingHistory: [], evidenceRecords: [], executionAttempts: [] });
  assert.equal(indicators.knowledge.value, 0);
  assert.equal(indicators.evidence.value, 0);
  assert.equal(indicators.creativity.value, 0);
  assert.equal(indicators.execution.value, 0);
  assert.equal(indicators.clarity.value, 0);
});

test("clarity rewards a single dominant match over a tied one", () => {
  const dominant = computeIndicators({
    routingHistory: [{ matched: ["learn"], scores: { learn: 4, explain: 0 } }],
    evidenceRecords: [], executionAttempts: [],
  });
  const tied = computeIndicators({
    routingHistory: [{ matched: ["learn", "explain"], scores: { learn: 2, explain: 2 } }],
    evidenceRecords: [], executionAttempts: [],
  });
  assert.ok(dominant.clarity.value > tied.clarity.value, `${dominant.clarity.value} should exceed ${tied.clarity.value}`);
});

test("clarity is exactly zero when the latest routing matched nothing", () => {
  const indicators = computeIndicators({
    routingHistory: [{ matched: [], scores: { learn: 0, explain: 0 } }],
    evidenceRecords: [], executionAttempts: [],
  });
  assert.equal(indicators.clarity.value, 0);
});

test("evidence indicator is a direct, documented mapping of the strongest evidence state", () => {
  const observed = computeIndicators({ routingHistory: [], evidenceRecords: [{ state: "OBSERVED" }], executionAttempts: [] });
  const validated = computeIndicators({ routingHistory: [], evidenceRecords: [{ state: "OBSERVED" }, { state: "VALIDATED" }], executionAttempts: [] });
  assert.equal(observed.evidence.value, 0.25);
  assert.equal(validated.evidence.value, 0.75);
  assert.ok(validated.evidence.value > observed.evidence.value);
});

test("knowledge grows with accumulated routing + evidence but saturates at 1", () => {
  const many = computeIndicators({
    routingHistory: Array.from({ length: 20 }, () => ({ matched: [], scores: {} })),
    evidenceRecords: Array.from({ length: 20 }, () => ({ state: "OBSERVED" })),
    executionAttempts: [],
  });
  assert.equal(many.knowledge.value, 1);
});

test("execution indicator is the literal success ratio, zero attempts means zero (not undefined optimism)", () => {
  const none = computeIndicators({ routingHistory: [], evidenceRecords: [], executionAttempts: [] });
  const halfSucceeded = computeIndicators({
    routingHistory: [], evidenceRecords: [],
    executionAttempts: [{ outcome: "SUCCEEDED" }, { outcome: "FAILED" }],
  });
  const allSucceeded = computeIndicators({
    routingHistory: [], evidenceRecords: [],
    executionAttempts: [{ outcome: "SUCCEEDED" }, { outcome: "SUCCEEDED" }],
  });
  assert.equal(none.execution.value, 0);
  assert.equal(halfSucceeded.execution.value, 0.5);
  assert.equal(allSucceeded.execution.value, 1);
});

test("creativity is labeled as a proxy and grows with distinct route combinations, capped at 1", () => {
  const oneRoute = computeIndicators({
    routingHistory: [{ matched: ["learn", "explain"], scores: {} }],
    evidenceRecords: [], executionAttempts: [],
  });
  const threeDistinctRoutes = computeIndicators({
    routingHistory: [
      { matched: ["learn"], scores: {} },
      { matched: ["create", "design"], scores: {} },
      { matched: ["analyze", "discover", "execute"], scores: {} },
    ],
    evidenceRecords: [], executionAttempts: [],
  });
  assert.equal(oneRoute.creativity.isProxy, true);
  assert.ok(threeDistinctRoutes.creativity.value > oneRoute.creativity.value);
  assert.equal(threeDistinctRoutes.creativity.value, 1);
});

test("re-routing to the SAME combination repeatedly does not inflate creativity", () => {
  const repeated = computeIndicators({
    routingHistory: [
      { matched: ["learn", "explain"], scores: {} },
      { matched: ["explain", "learn"], scores: {} }, // same set, different order
      { matched: ["learn", "explain"], scores: {} },
    ],
    evidenceRecords: [], executionAttempts: [],
  });
  assert.ok(repeated.creativity.value < 0.5, "three routing passes over one combination should not read as highly creative");
});

test("every indicator carries a non-empty basis string explaining how it was computed", () => {
  const indicators = computeIndicators({
    routingHistory: [{ matched: ["learn"], scores: { learn: 1 } }],
    evidenceRecords: [{ state: "OBSERVED" }],
    executionAttempts: [{ outcome: "SUCCEEDED" }],
  });
  for (const key of ["knowledge", "evidence", "creativity", "execution", "clarity"]) {
    assert.ok(indicators[key].basis && indicators[key].basis.length > 0, `${key} has no basis string`);
  }
});
