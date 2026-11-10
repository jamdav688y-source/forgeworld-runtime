# ADR-0005 — Explicit conflicts, not last-writer-wins

**Status:** accepted · 2026-11-10

**Context.** Phone and PC edit offline. Device clocks are not trustworthy. The directive forbids
silent destructive merges.

**Decision.** Causal heads per state key (see SYNC_PROTOCOL.md §5). Disagreeing heads produce
CONFLICTED with no value, plus a recorded conflict. Only a human `CONFLICT_RESOLVED` event, whose
parents are the heads, resolves it. A device that signs two different events with the same
sequence number is recorded as EQUIVOCATION and quarantined.

**Consequences.** Some conflicts need a human. Drafting treats a conflicted fact as unknown, so it
neither re-asks blindly nor guesses.
