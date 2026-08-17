import { test } from "node:test";
import assert from "node:assert/strict";
import { evaluateAuthority, AuthorityState, isAutonomouslyExecutable, listCapabilities, evidenceAtLeast, EvidenceState } from "../lib/governance.js";

test("unknown capability returns UNKNOWN, never ALLOWED", () => {
  const decision = evaluateAuthority("TOTALLY_MADE_UP_CAPABILITY");
  assert.equal(decision.decision, AuthorityState.UNKNOWN);
  assert.notEqual(decision.decision, AuthorityState.ALLOWED);
});

test("CREATE_MISSION is ALLOWED and autonomously executable", () => {
  const decision = evaluateAuthority("CREATE_MISSION");
  assert.equal(decision.decision, AuthorityState.ALLOWED);
  assert.equal(isAutonomouslyExecutable(decision.decision), true);
});

test("MODIFY_CAPABILITY_POLICY is HUMAN_ONLY and NOT autonomously executable", () => {
  const decision = evaluateAuthority("MODIFY_CAPABILITY_POLICY");
  assert.equal(decision.decision, AuthorityState.HUMAN_ONLY);
  assert.equal(isAutonomouslyExecutable(decision.decision), false);
});

test("TRIGGER_PHONE_DEPLOY requires approval and flags approvalRequired", () => {
  const decision = evaluateAuthority("TRIGGER_PHONE_DEPLOY");
  assert.equal(decision.decision, AuthorityState.REQUIRES_APPROVAL);
  assert.equal(decision.approvalRequired, true);
  assert.equal(isAutonomouslyExecutable(decision.decision), false);
});

test("bounded capability with no prior run is trivially satisfied, not UNKNOWN", () => {
  const decision = evaluateAuthority("RUN_RECONCILE_SCAN", {});
  assert.equal(decision.decision, AuthorityState.ALLOWED_BOUNDED);
});

test("bounded capability run too recently is DENIED", () => {
  const decision = evaluateAuthority("RUN_RECONCILE_SCAN", { lastRunAt: Date.now() - 5000 });
  assert.equal(decision.decision, AuthorityState.DENIED);
});

test("bounded capability run long enough ago is ALLOWED_BOUNDED again", () => {
  const decision = evaluateAuthority("RUN_RECONCILE_SCAN", { lastRunAt: Date.now() - 61_000 });
  assert.equal(decision.decision, AuthorityState.ALLOWED_BOUNDED);
});

test("listCapabilities returns every capability the policy table defines", () => {
  const caps = listCapabilities();
  assert.ok(caps.includes("CREATE_MISSION"));
  assert.ok(caps.includes("TRIGGER_PHONE_DEPLOY"));
  assert.ok(caps.includes("MODIFY_CAPABILITY_POLICY"));
  assert.equal(caps.length, new Set(caps).size, "no duplicate capability names");
});

test("evidenceAtLeast respects the UNKNOWN < OBSERVED < SUPPORTED < VALIDATED < INSTITUTIONALIZED order", () => {
  assert.equal(evidenceAtLeast(EvidenceState.VALIDATED, EvidenceState.OBSERVED), true);
  assert.equal(evidenceAtLeast(EvidenceState.OBSERVED, EvidenceState.VALIDATED), false);
  assert.equal(evidenceAtLeast(EvidenceState.UNKNOWN, EvidenceState.UNKNOWN), true);
  assert.equal(evidenceAtLeast(EvidenceState.INSTITUTIONALIZED, EvidenceState.VALIDATED), true);
});

test("every AuthorityState value referenced by the policy table is a real enum member", () => {
  const validStates = new Set(Object.values(AuthorityState));
  for (const cap of listCapabilities()) {
    const decision = evaluateAuthority(cap, { lastRunAt: Date.now() - 999_999 });
    assert.ok(validStates.has(decision.decision), `${cap} returned an invalid state: ${decision.decision}`);
  }
});
