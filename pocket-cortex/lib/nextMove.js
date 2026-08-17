// Next-right-move generation.
//
// Produces exactly one concrete, small, doable next action for a
// mission, derived from its actual recorded state -- never a generic
// platitude, and never invented independently of what's in the
// database. Priority order below is deliberate: an unresolved approval
// or a missing route always outranks "keep going," matching the
// governing chain's insistence that capability/authority problems block
// forward progress rather than being silently worked around.

import { EvidenceState } from "./governance.js";

export function generateNextMove({ mission, routingHistory, evidenceRecords, executionAttempts }) {
  const latestExecution = executionAttempts[executionAttempts.length - 1];
  if (latestExecution && (latestExecution.outcome === "AWAITING_APPROVAL" || latestExecution.outcome === "BLOCKED")) {
    return {
      text: `Resolve the pending ${latestExecution.capability} approval before continuing -- it is currently ${latestExecution.outcome}.`,
      basis: `Latest execution attempt (${latestExecution.id}) is unresolved.`,
    };
  }

  if (!mission.route || mission.route.length === 0) {
    return {
      text: "Rephrase the goal with a clearer action word (learn, build, analyze, design, explain, discover, execute) so it can be routed to a capability.",
      basis: "No capability has matched this mission's goal text yet.",
    };
  }

  const strongestEvidence = evidenceRecords.reduce((acc, r) => {
    const order = [EvidenceState.UNKNOWN, EvidenceState.OBSERVED, EvidenceState.SUPPORTED, EvidenceState.VALIDATED, EvidenceState.INSTITUTIONALIZED];
    return order.indexOf(r.state) > order.indexOf(acc) ? r.state : acc;
  }, EvidenceState.UNKNOWN);

  if (strongestEvidence === EvidenceState.UNKNOWN) {
    return {
      text: "Confirm whether the current route actually matches your intent -- that confirmation is what moves this mission's evidence from UNKNOWN to OBSERVED.",
      basis: `Route matched (${mission.route.join(", ")}) but no evidence has been recorded yet.`,
    };
  }

  if (strongestEvidence === EvidenceState.OBSERVED && routingHistory.length < 2) {
    return {
      text: "Restate the goal a different way and see if the same route holds -- a second, independent routing pass is what moves evidence from OBSERVED to SUPPORTED.",
      basis: "Only one routing pass recorded so far; evidence has not yet been independently corroborated.",
    };
  }

  if (mission.stage === "INTENT") {
    return { text: "Move this mission into ROUTE -- the intent has capability matches ready to act on.", basis: "Mission stage is still INTENT despite having a matched route." };
  }

  if (mission.stage === "ROUTE" || mission.stage === "WORK") {
    if (executionAttempts.length === 0) {
      return {
        text: "Record a concrete execution attempt for the leading routed capability, even a small one, so EXECUTION reflects real progress instead of zero.",
        basis: `Stage is ${mission.stage} with evidence at ${strongestEvidence}, but no execution has been attempted.`,
      };
    }
    return { text: "Review what came out of the routed work before deciding the next execution step.", basis: `Stage is ${mission.stage} with ${executionAttempts.length} execution attempt(s) already recorded.` };
  }

  if (mission.stage === "REVIEW") {
    return { text: "Decide: is this mission ready to execute further, or does it need another routing pass first?", basis: "Mission is in REVIEW stage." };
  }

  return { text: "This mission's active cycle is complete. Start a new mission, or revisit this one from HISTORY if new information arrives.", basis: `Mission stage is ${mission.stage}.` };
}
