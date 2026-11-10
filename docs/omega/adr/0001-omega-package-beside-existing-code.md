# ADR-0001 — A new `omega/` package beside existing code

**Status:** accepted · 2026-11-10

**Context.** The directive asks for a dual-node substrate. This branch has a tested CXP kernel
(`cognition/`), an evidence envelope (`evidence_envelope/`) and a mobile research store, but no
identity, pairing, transport or sync. Code refers to `substrate/` and `fabric/` packages
(including a `CapabilityPromotionGate`) that are not on this branch.

**Decision.** Build `omega/` as a new package. Reuse `cognition.cxp.canonical_bytes` for canonical
JSON. Modify no existing module. Do not name anything `substrate/` or `fabric/`.

**Consequences.** No regression risk to the 505 existing tests (re-run: unchanged). When
`substrate/` is merged, its `CapabilityPromotionGate` and `omega.evolution.PromotionGate` must be
reconciled: omega's gate should defer to it, or be retired, through a human-reviewed change.
CXP records and omega events are separate formats (ADR-0003 explains why).
