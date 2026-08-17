import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { checkCapability } from "../lib/capability.js";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

test("built-in capabilities are always available (they are this running process)", () => {
  for (const name of ["CREATE_MISSION", "UPDATE_ROUTE", "RECORD_EVIDENCE", "RECORD_EXECUTION_ATTEMPT", "EXPORT_MISSION_DATA", "MODIFY_CAPABILITY_POLICY"]) {
    const result = checkCapability(name, REPO_ROOT);
    assert.equal(result.available, true, `${name} should always be available`);
  }
});

test("RUN_RECONCILE_SCAN capability check finds the real script in this repo", () => {
  const result = checkCapability("RUN_RECONCILE_SCAN", REPO_ROOT);
  assert.equal(result.available, true, result.evidence);
  assert.match(result.evidence, /forge_reconcile\.py present: true/);
});

test("capability check for a nonexistent script correctly reports unavailable", () => {
  const result = checkCapability("RUN_RECONCILE_SCAN", "/tmp/definitely-not-a-real-forgeworld-checkout");
  assert.equal(result.available, false);
});

test("unknown capability name is unavailable, not assumed available", () => {
  const result = checkCapability("SOME_MADE_UP_CAPABILITY", REPO_ROOT);
  assert.equal(result.available, false);
});

test("capability and authority are genuinely independent: TRIGGER_PHONE_DEPLOY authority is REQUIRES_APPROVAL regardless of whether forge_deploy.py exists yet", async () => {
  const { evaluateAuthority } = await import("../lib/governance.js");
  const authority = evaluateAuthority("TRIGGER_PHONE_DEPLOY");
  // capability may be true or false depending on whether forge_deploy.py
  // has been created in this checkout yet -- authority must not change
  // either way, since the two are evaluated independently.
  assert.equal(authority.decision, "REQUIRES_APPROVAL");
});
