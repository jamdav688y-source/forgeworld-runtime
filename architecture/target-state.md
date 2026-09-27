# ForgeWorld Target State

Summary of MISSION_ID: FORGEWORLD-CONTINUITY-FABRIC-001's target
architecture (Sections 0–13 of the mission brief), restated against what
already exists so the gap is visible rather than re-describing the brief
verbatim. This is a target, not a plan of record — no construction is
authorized by this document.

## Primary design law

Accumulate the *demonstrated ability to discover, construct, test, govern,
verify, preserve, recombine, and improve* the workflow a given objective
requires — not a growing pile of workflows themselves. Everything built in
this repository so far (see `current-state.md`) is compatible with this
law: every package is a narrow, tested capability with an honest failure
mode, not a workflow template.

## Non-negotiable invariant (unchanged, already partially enforced in code)

`KNOWLEDGE != CAPABILITY != AUTHORITY != VERIFIED_OUTCOME`. The existing
codebase already enforces fragments of this structurally: `Manifest`,
`ContentReadResult`, `InferenceResult`, and `FabricReceipt` all carry fixed,
non-overridable `evidence_status`/`promotion_status`/`trust_status`
properties that cannot be set to anything but "not yet." What does **not**
exist yet is a *general* mechanism that prevents a capability, a memory
item, or an authority grant from silently becoming more than it has earned
— see `gap-matrix.md` for exactly where this is proven vs. absent.

## Twenty required primitives — target role (see `gap-matrix.md` for current classification)

1. **PermanentMemory** — durable, typed memory beyond one conversation.
2. **ContextCompiler** — builds the smallest relevant context per objective.
3. **IdentityFabric** — identity across models/devices/sessions/agents.
4. **EventFabric** — typed, causally-linked, replay-safe event log.
5. **CapabilityGraph** — capabilities as demonstrated-ability nodes with state.
6. **CapabilityResolver** — picks capabilities for an objective.
7. **SkillRegistry** — versioned, invokable skill/capability catalog.
8. **WorkflowCompiler** — compiles the smallest executable graph for an objective.
9. **CapabilityRecombinationEngine** — discovers higher-order capabilities.
10. **ForgeSentinel** — continuous adversarial-risk analysis.
11. **GovernanceEngine** — policy evaluation over proposed transitions.
12. **AuthorityVerifier** — verifies actor×action×context×time×policy.
13. **ExecutionFabric** — unified, provider-neutral execution surface.
14. **EvidenceLedger** — durable record of what actually happened.
15. **CapabilityPromotionGate** — GENERATED→...→PROMOTED gate with counterevidence retained.
16. **DeviceTransport** — phone↔PC (and beyond) physical transport.
17. **Synchronization/Reconciliation** — safe convergence of divergent checkouts/state.
18. **ProviderRegistry** — cognition/execution providers as replaceable, selectable entries.
19. **Relationship/CommercialState** — evidence-backed commercial lifecycle.
20. **HumanApprovalInterface** — where a human, not a policy, must decide.

## Target cognitive loop

```
OBJECTIVE → CONTEXT RESOLUTION → CAPABILITY RESOLUTION → SKILL COMPOSITION →
WORKFLOW COMPILATION → AGENT/MODEL/PROVIDER ASSIGNMENT → SENTINEL ANALYSIS →
GOVERNANCE/AUTHORITY RESOLUTION → EXECUTION → VERIFICATION → EVIDENCE RECEIPT →
CAPABILITY PROMOTION → CAPABILITY RECOMBINATION → PERMANENT MEMORY →
UPDATED CAPABILITY GRAPH ↺
```

Today, the closest real analogue to any full pass through this loop is the
`fabric/` round trip: `RemoteCapabilityRequest` (objective + authority
context) → `process_remote_capability_request()` (resolution + governance
+ execution, all in one function) → `RemoteCapabilityResult` +
`FabricReceipt` (verification + evidence). It covers roughly six of the
sixteen loop stages, in one un-decomposed function, for exactly one
capability (`content_read`) — a genuine but narrow proof, not the loop
itself.

## What this document deliberately does not do

It does not propose an implementation order, a schema, or a file layout for
any of the twenty primitives. That is construction, and construction is not
authorized in Phase 0. `gap-matrix.md` states what's missing; the smallest
next microphase is proposed once, at the end of this recovery, for operator
authorization.
