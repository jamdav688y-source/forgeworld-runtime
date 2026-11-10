# ADR-0007 — Bounded evolution: agents propose, the gate measures, humans decide

**Status:** accepted · 2026-11-10

**Decision.** `omega/evolution.py` records falsifiable experiments, runs the regression command
for real, pins a governance digest (governance/, omega/policy.py, events.py, evolution.py,
tasks.py), checks that the rollback commit exists, and records the verdict. `PROMOTION_DECISION`
is human-only, and PROMOTE is refused unless the verdict is ELIGIBLE. Each experiment gets at
most three evaluations. Nothing in the package edits code or loops on its own. The specialist
panel (`omega/agents.py`) only writes UNVERIFIED `AGENT_OPINION` events.

**Consequences.** No autonomous self-modification. Changing governance always takes a
human-reviewed commit, and the gate's pinned digest has to be updated deliberately afterwards.
