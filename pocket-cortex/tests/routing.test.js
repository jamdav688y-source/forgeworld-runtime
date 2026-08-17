import { test } from "node:test";
import assert from "node:assert/strict";
import { routeIntent } from "../lib/routing.js";

test("empty goal text routes to nothing with an honest rationale", () => {
  const result = routeIntent("   ");
  assert.deepEqual(result.matched, []);
  assert.match(result.rationale, /Empty goal text/);
});

test("gibberish with no keyword matches routes to nothing", () => {
  const result = routeIntent("qwzxjklv poiuytr");
  assert.deepEqual(result.matched, []);
  assert.match(result.rationale, /No keyword/);
});

test("'teach' triggers the phrase rule for LEARN/EXPLAIN/ANALYZE", () => {
  const result = routeIntent("Teach me something I do not understand.");
  assert.deepEqual(result.matched, ["learn", "explain", "analyze"]);
  assert.match(result.rationale, /phrase rule/);
});

test("keyword scoring ranks by hit count and names which keywords fired", () => {
  const result = routeIntent("Build and create a new draft.");
  assert.equal(result.matched[0], "create");
  assert.match(result.rationale, /CREATE \(matched: create, build, draft\)/);
});

test("routing is a pure function of its input text (deterministic)", () => {
  const a = routeIntent("Analyze this problem for me.");
  const b = routeIntent("Analyze this problem for me.");
  assert.deepEqual(a, b);
});

test("matched list never exceeds 3 capabilities", () => {
  const result = routeIntent("learn teach explain understand analyze solve create build design visual execute run");
  assert.ok(result.matched.length <= 3);
});
