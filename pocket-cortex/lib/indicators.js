// Truthful Knowledge / Evidence / Creativity / Execution / Clarity
// indicators.
//
// The previous prototype (pocket-cortex/app.js on
// claude/pocket-cortex-title-screen-hvf7j8) hardcoded these as constants
// -- { KNOWLEDGE: 0.72, EVIDENCE: 0.58, CREATIVITY: 0.84, EXECUTION: 0.66,
// CLARITY: 0.91 } -- labeled "DEMONSTRATION STATE" / "DEMO CONTENT" in
// its own UI. That label was honest about what it was. This module
// replaces the hardcoded numbers with real computations over a mission's
// actual recorded state, each with its exact formula documented right
// here so "truthful" means "inspectable," not "trust us." Every
// indicator returns both a 0..1 value AND a plain-language `basis`
// string describing what it was actually computed from, so the UI never
// has to show a number with no explanation.
//
// Explicit limitation, stated rather than hidden: CREATIVITY has no
// direct machine-measurable definition. Rather than fabricate a
// precise-looking score for something unmeasurable, this module computes
// a disclosed PROXY (route diversity across the mission's routing
// history) and labels it as a proxy, not a quality judgment.

import { EvidenceState, evidenceAtLeast } from "./governance.js";

function clamp01(x) {
  return Math.max(0, Math.min(1, x));
}

const EVIDENCE_NUMERIC = {
  [EvidenceState.UNKNOWN]: 0,
  [EvidenceState.OBSERVED]: 0.25,
  [EvidenceState.SUPPORTED]: 0.5,
  [EvidenceState.VALIDATED]: 0.75,
  [EvidenceState.INSTITUTIONALIZED]: 1,
};

function strongestEvidenceState(evidenceRecords) {
  let strongest = EvidenceState.UNKNOWN;
  for (const rec of evidenceRecords) {
    if (evidenceAtLeast(rec.state, strongest)) strongest = rec.state;
  }
  return strongest;
}

/**
 * CLARITY -- how unambiguous the most recent intent routing was.
 * Formula: given the latest routing decision's per-capability keyword
 * scores, clarity rewards a single dominant match and penalizes a flat
 * or empty score distribution. top1/top2 are the two highest scores.
 *   clarity = 0                                   if no routing yet, or top1 == 0
 *   clarity = 0.7 * (top1 - top2) / top1 + 0.3 * min(top1 / 4, 1)   otherwise
 * The 0.7/0.3 weighting favors "how separated is the winner from the
 * runner-up" over "how many keywords fired," since a single very strong
 * signal should read as clearer than several weak, tied ones.
 */
function computeClarity(routingHistory) {
  if (!routingHistory.length) {
    return { value: 0, basis: "No intent has been routed yet." };
  }
  const latest = routingHistory[routingHistory.length - 1];
  const scores = Object.values(latest.scores || {}).sort((a, b) => b - a);
  const top1 = scores[0] || 0;
  const top2 = scores[1] || 0;
  if (top1 === 0) {
    return { value: 0, basis: "The most recent goal text matched no known capability keywords." };
  }
  const value = clamp01(0.7 * ((top1 - top2) / top1) + 0.3 * Math.min(top1 / 4, 1));
  return {
    value,
    basis: `Latest routing: top match scored ${top1}, next closest scored ${top2} (from keyword overlap, see ROUTE panel rationale).`,
  };
}

/**
 * EVIDENCE -- directly reads the mission's strongest qualified evidence
 * state (see governance.js EvidenceState) and maps it onto 0..1. This is
 * the most literal of the five: it is not a proxy, it is the evidence
 * ladder itself expressed as a number.
 */
function computeEvidence(evidenceRecords) {
  const strongest = strongestEvidenceState(evidenceRecords);
  return {
    value: EVIDENCE_NUMERIC[strongest],
    basis: `Strongest recorded evidence state for this mission: ${strongest} (${evidenceRecords.length} record(s) total).`,
  };
}

/**
 * KNOWLEDGE -- how much has actually accumulated about this mission:
 * every routing decision and every evidence record is one more real
 * data point the system has about what this mission is and how it's
 * going. Saturates rather than growing unbounded, since accumulation
 * past a point stops meaningfully changing how "known" a mission is.
 *   knowledge = min(1, 0.12 * routingCount + 0.10 * evidenceCount)
 */
function computeKnowledge(routingHistory, evidenceRecords) {
  const value = clamp01(0.12 * routingHistory.length + 0.1 * evidenceRecords.length);
  return {
    value,
    basis: `${routingHistory.length} routing decision(s) and ${evidenceRecords.length} evidence record(s) accumulated for this mission.`,
  };
}

/**
 * EXECUTION -- literal success ratio of recorded execution attempts.
 * Zero attempts means zero execution progress (not an optimistic
 * default) -- an unattempted mission has not executed anything, and
 * this indicator says so plainly rather than assuming good faith.
 */
function computeExecution(executionAttempts) {
  if (!executionAttempts.length) {
    return { value: 0, basis: "No execution has been attempted yet." };
  }
  const succeeded = executionAttempts.filter((a) => a.outcome === "SUCCEEDED").length;
  const value = clamp01(succeeded / executionAttempts.length);
  return {
    value,
    basis: `${succeeded} of ${executionAttempts.length} recorded execution attempt(s) succeeded.`,
  };
}

/**
 * CREATIVITY -- explicitly a disclosed PROXY, not a quality judgment:
 * how many DISTINCT capability-route combinations this mission has been
 * routed through (re-routing to a materially different combination of
 * capabilities is the only signal available to a routing system that it
 * can honestly call "exploring different directions").
 *   creativity = min(1, distinctRouteCombinations / 3)
 */
function computeCreativity(routingHistory) {
  const combos = new Set(routingHistory.map((r) => r.matched.slice().sort().join("+")));
  const value = clamp01(combos.size / 3);
  return {
    value,
    basis: `${combos.size} distinct capability-route combination(s) explored across this mission's routing history. Proxy metric, not a judgment of idea quality.`,
  };
}

export function computeIndicators({ routingHistory = [], evidenceRecords = [], executionAttempts = [] }) {
  const clarity = computeClarity(routingHistory);
  const evidence = computeEvidence(evidenceRecords);
  const knowledge = computeKnowledge(routingHistory, evidenceRecords);
  const execution = computeExecution(executionAttempts);
  const creativity = computeCreativity(routingHistory);

  return {
    knowledge: { label: "KNOWLEDGE", ...knowledge },
    evidence: { label: "EVIDENCE", ...evidence },
    creativity: { label: "CREATIVITY", ...creativity, isProxy: true },
    execution: { label: "EXECUTION", ...execution },
    clarity: { label: "CLARITY", ...clarity },
  };
}
