// Server-side intent routing: source of truth for what gets persisted.
//
// The client (app.js) keeps its own copy of KEYWORD_MAP for instant
// as-you-type visual feedback on the constellation (recomputing this on
// every keystroke over a network round-trip would feel laggy on a phone
// and burn battery/data for no benefit) -- but the routing decision that
// actually gets written to the database, and the rationale shown in the
// ROUTE panel, always comes from this module via the API, not from the
// client's local guess. If the two ever disagree, this file wins.

export const KEYWORD_MAP = {
  learn: ["learn", "teach", "understand", "study", "explain to me", "how does", "what is", "curious", "tutorial"],
  explain: ["explain", "clarify", "why", "meaning", "define", "breakdown", "walk me through", "understand"],
  analyze: ["analyze", "solve", "problem", "evaluate", "compare", "diagnose", "investigate", "review", "assess", "debug"],
  discover: ["discover", "find", "search", "explore", "research", "identify", "uncover", "solve"],
  create: ["create", "build", "make", "write", "generate", "compose", "draft", "produce"],
  design: ["design", "image", "visual", "layout", "art", "style", "aesthetic", "mockup", "picture"],
  execute: ["execute", "run", "do it", "solve", "perform", "automate", "ship", "deploy", "finish"],
};

const PHRASE_RULES = [
  { test: (t) => t.includes("teach"), nodes: ["learn", "explain", "analyze"] },
  { test: (t) => t.includes("create") && /image|picture|art|visual|logo/.test(t), nodes: ["create", "design", "discover"] },
  { test: (t) => t.includes("design") && /interface|screen|layout|\bui\b|workspace/.test(t), nodes: ["create", "design", "discover"] },
  { test: (t) => t.includes("solve") || t.includes("problem"), nodes: ["analyze", "discover", "execute"] },
];

export function scoreText(text) {
  const lower = text.toLowerCase();
  const scores = {};
  const matchedKeywords = {};
  for (const id of Object.keys(KEYWORD_MAP)) {
    const hits = KEYWORD_MAP[id].filter((kw) => lower.includes(kw));
    scores[id] = hits.length;
    if (hits.length) matchedKeywords[id] = hits;
  }
  return { scores, matchedKeywords };
}

/**
 * Route a goal to 0-3 capabilities and produce a human-readable
 * rationale that names the actual rule or keywords that fired -- never
 * a generic "matched via routing logic" placeholder.
 */
export function routeIntent(text) {
  const lower = text.toLowerCase().trim();
  if (!lower) {
    return { matched: [], scores: {}, rationale: "Empty goal text; nothing to route." };
  }

  const phraseRule = PHRASE_RULES.find((r) => r.test(lower));
  const { scores, matchedKeywords } = scoreText(lower);

  if (phraseRule) {
    return {
      matched: phraseRule.nodes,
      scores,
      rationale: `Matched a phrase rule (not just keyword scoring): the goal text triggered a specific pattern associated with ${phraseRule.nodes.join(", ").toUpperCase()}.`,
    };
  }

  const matched = Object.keys(scores)
    .filter((id) => scores[id] > 0)
    .sort((a, b) => scores[b] - scores[a])
    .slice(0, 3);

  if (!matched.length) {
    return { matched: [], scores, rationale: "No keyword from any capability's vocabulary appeared in the goal text." };
  }

  const parts = matched.map((id) => `${id.toUpperCase()} (matched: ${matchedKeywords[id].join(", ")})`);
  return {
    matched,
    scores,
    rationale: `Keyword match, ranked by hit count: ${parts.join("; ")}.`,
  };
}
