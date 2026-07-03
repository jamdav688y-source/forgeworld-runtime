# PATTERN_LIBRARY.md

Conventions established in `substrate-runtime/`. Follow these when extending
the codebase rather than inventing parallel approaches.

## Interface-in-`core`, implementation-in-`app` (+ in-memory fake)

Every storage seam is a plain interface in `core/repository/` with two
implementations:
- an in-memory `ConcurrentHashMap`-backed one in `core` (test/default use),
- a Room-backed one in `app/data/repository/`.

`core` never imports Android or Room. This is what lets `gradle :core:test`
verify real logic on a plain JDK with no emulator. When adding a new kind of
persisted thing, add the interface + in-memory fake to `core` first, write
its tests against the fake, *then* add the Room entity/DAO/impl in `app`.

## Deterministic ids for anything that should be reinforced, not duplicated

- Domain anchor nodes: `"domain:$NodeType"`
- Topic nodes: `"topic:${slug(label)}"`
- Project nodes: `"project:${slug(label)}"`
- Actor nodes: `"user:${slug(actor)}"`
- Edges: `"edge:$EdgeType:$fromNodeId:$toNodeId"`

`GraphEdgeOps.reinforce()` is the one place edges get created/strengthened —
always route new edge writes through it rather than constructing `GraphEdge`
and calling `upsertEdge` directly, or you'll silently reintroduce duplicate
edges between the same node pair.

## Every pipeline stage logs exactly one `AuditTrailEntry`

`PipelineStage` holds the canonical stage-name constants. If you add a stage
to `EventPipeline.submit()`, add its constant there and call `log(...)`
exactly once for it. `EventPipelineTest` asserts `auditTrail.size >= 12` —
update that count if you add stages.

## Governance violations carry a `blocking: Boolean`

Don't add a new `GovernanceViolation` without deciding, explicitly, whether
it should reject the event (`blocking = true`) or just hold it for review
(`blocking = false`). `ExecutionDecisionEngine` treats these very
differently (REJECT vs HOLD) — see ENGINEERING_MEMORY.md for why blanket
rejection is wrong for expected-common cases like low classification
confidence.

## Assessment/decision types always carry their own evidence

`Classification.matchedKeywords`, `GovernanceDecision.violations`,
`CommercialAssessment.signals`, `ExecutionOutcome.reasons` — every
inspectable decision in this pipeline names the concrete inputs that produced
it. When adding a new scoring/decision stage, follow this shape: the numeric
result plus a list of the human-readable signals behind it. This is what
makes the Audit screen meaningful instead of a bare number.

## Reuse `core` math in reactive `app` code — never re-derive it

`NeuralLandscapeViewModel` calls `substrate.core.pipeline.ActivationPulseGenerator.decayedActivation()`
directly rather than reimplementing decay math for the UI's live-refresh
loop. If server-side and UI-side decay ever drift, the visualization stops
being "a direct visualization of runtime state" (Runtime Invariant #7) and
becomes decoration. Same principle applies to any other `core` computation
the UI needs to display live.

## Testing shape for a new pipeline stage

Follow the existing four test files as the template:
- `EventClassifierTest.kt` — pure function, table of inputs/expected outputs.
- `VectorIndexTest.kt` — numeric properties (identical→1.0, unrelated→low,
  empty→0.0), not exact-value snapshots that will be brittle to tuning.
- `GovernanceValidatorTest.kt` — one test per violation rule, both the
  "triggers" and "well-formed input passes clean" cases.
- `EventPipelineTest.kt` — end-to-end, using `InMemory*Repository` +
  `EventPipeline` with an injectable clock (`nowMillisProvider`), asserting
  on `PipelineResult` fields, not on repository internals.

## Injectable clock, never `System.currentTimeMillis()` inline in logic

`EventPipeline`'s constructor takes `nowMillisProvider: () -> Long`.
Anything that needs "now" for decay/reinforcement math should receive it as
a parameter (see `ActivationPulseGenerator.decayedActivation(node, nowMillis)`)
rather than calling the system clock directly, so tests can control time
deterministically (`EventPipelineTest` uses a mutable `LongArray` as a fake
clock to advance time between two `submit()` calls).
