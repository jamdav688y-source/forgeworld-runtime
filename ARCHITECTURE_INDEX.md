# ARCHITECTURE_INDEX.md

Full system map of this repository. Two independent systems live here; this
document covers both, in the order they were built.

---

## §1. FORGEWORLD doctrine/bash scaffold (pre-existing, unmodified)

Surveyed in full during the 2026-07-03 architectural discovery pass (see
MISSION_LOG.md, "FORGEWORLD_ARCH_DISCOVERY_PASS"). Summary preserved here as
permanent memory; nothing in this section was changed by this build.

### Topology

63 files, 25 top-level directories, single git commit at time of survey. Pure
Bash + Markdown + JSON, no package manager, no tests, no CI.

```
governance/   — CONSTITUTION_v1 → v3, EVOLUTION_DIRECTIVE_v1, PHASE_5_RUNTIME,
                master_persistence_directive. Prose doctrine only.
doctrine/     — FORGEWORLD_RUNTIME.md variants; governance.md, identity.md,
                linkedin_protocol.md are empty stubs.
events/ memory/ npc/ npcs/ factions/ reputation/ relationships/ consequences/
world/ future/ council_reviews/ — append-only .log files, one directory per
                doctrine "layer" in the causal chain.
diagnostics/  — read-only tail/exists-check scripts, not real validation.
scripts/      — forge (dispatcher) + forge-*.sh (overlapping single-purpose
                siblings).
commands/     — FORGE_COMMANDS.md, a command-language spec with no matching
                implementation for REQUEST_BUILD / REQUEST_REVIEW / EXPORT.
```

### Runtime execution map

Two execution surfaces, no automation, no triggers (deliberate — see
`governance/PHASE_5_RUNTIME.txt`: "do not run loops... act only when manually
invoked"):

- **Installers** (`install_*.sh`): idempotent, heredoc-based, each writes
  doctrine text + a companion script, then runs it.
- **Manual commands**: `log_event.sh`, `resolve_event.sh`, `runtime.sh`,
  `diagnostics/*_check.sh`, `scripts/forge <verb>`.

All 16 scripts hardcode `BASE="$HOME/forgeworld"` and a Termux shebang — none
resolve their own path, so none run against this checkout without manual
path surgery.

### Governance model (doctrine, not enforced)

Causal chain: `EVENT → EVIDENCE → MEMORY → REPUTATION → RELATIONSHIP →
FACTION → GOVERNANCE → CONSEQUENCE → WORLD_STATE → FUTURE_STATE`, reviewed
through nine "Council of Minds" perspectives (Historian, Architect, Governor,
Strategist, Verifier, Optimizer, Explorer, Humanist, Witness). `resolve_event.sh`
mechanically echoes all nine question templates for every event — no actual
evaluation, no rejection path. This is the gap `substrate-runtime/` (§2)
closes: it is the first code in this repo's history where governance can
actually say no.

### Known defects (unfixed, out of scope for this build)

- Three divergent `world_state`/`player` JSON schemas that never reconcile.
- `scripts/forge-signal`: broken redirect silently discards captured signals.
- `inbox/capture.md`: corrupted entry from unvalidated `read -r` prompts.
- `npcs/network.md`: real personal names committed in plaintext, no redaction.

Full finding-by-finding detail is in the discovery pass transcript
(2026-07-03); this section is the durable summary.

---

## §2. `substrate-runtime/` — MICRO_SUBSTRATE_RUNTIME_V1 (new, this build)

Native Android (Kotlin) implementation of a governed event pipeline. Gradle
multi-module: `core` (pure JVM, tested) + `app` (Android, Room + Compose,
**unverified in this sandbox — no Android SDK available**).

### Module boundary

```
core/   — domain model, all 12 pipeline stages, repository interfaces,
          in-memory reference repositories. Zero Android dependency.
          Buildable/testable with `gradle :core:test` anywhere with a JDK.
app/    — Room entities/DAOs implementing core's repository interfaces,
          Jetpack Compose UI (Capture / Landscape / Audit screens),
          manual DI in SubstrateApplication.kt.
```

### The 12-stage pipeline (`substrate.core.orchestrator.EventPipeline`)

```
Capture → Normalize → Classify → Activation Pulse → Retrieve Related Memory
→ Relationship Expansion → Governance Validation → Commercial Opportunity
Analysis → Execution Decision → Evidence Recording → Relationship
Reinforcement → Render Updated Neural Landscape
```

All twelve stages run **unconditionally** for every event — a REJECTed or
HELD event still gets evidence and becomes searchable memory, because Runtime
Invariants #4 and #6 are stated unconditionally in the mission spec. Execution
outcome (`EXECUTE` / `HOLD` / `REJECT`) currently gates nothing beyond itself:
no external action is wired up yet, so it is observable state, not a live
switch. Every stage appends exactly one `AuditTrailEntry` (`PipelineStage.kt`
lists the canonical stage names).

| Stage | File | What it actually does |
|---|---|---|
| Capture | `pipeline/EventCapture.kt` | Assigns a UUID; this is the only place event ids are minted. |
| Normalize | `pipeline/EventNormalizer.kt` | Whitespace cleanup, extracts `#tag` / `@mention` / `project:x` / `#project:x`. |
| Classify | `pipeline/EventClassifier.kt` | Deterministic keyword scoring into one of 10 `NodeType`s, with a confidence score and matched-keyword list. |
| Activation Pulse | `pipeline/ActivationPulseGenerator.kt` | Exponential decay (6h half-life) + pulse boost — applied to nodes inside relationship expansion. |
| Retrieve Related Memory | `pipeline/VectorIndex.kt` + `MemoryRetriever.kt` | Bag-of-words term-frequency vectors, cosine similarity, small fixed stopword list, threshold 0.15. |
| Relationship Expansion | `pipeline/RelationshipGraphEngine.kt` | Materializes/reinforces SEMANTIC, TEMPORAL, PROJECT, USER, RUNTIME, DEPENDENCY edges. Deterministic node/edge ids so repeated activation reinforces instead of duplicating. |
| Governance Validation | `pipeline/GovernanceValidator.kt` | Encodes 6 checks derived from the 8 Runtime Invariants + Constitution v3 Core Laws; each violation is `blocking` or not. |
| Commercial Opportunity Analysis | `pipeline/CommercialOpportunityAnalyzer.kt` | Heuristic scorer: classification domain + keyword hits + explicit `@opportunity` tag, all listed in `signals`. |
| Execution Decision | `pipeline/ExecutionDecisionEngine.kt` | REJECT (blocking violation) > HOLD (non-blocking violation) > EXECUTE. |
| Evidence Recording | `pipeline/EvidenceRecorder.kt` | Creates/reuses an `EvidenceRecord` per event id (dedup, not append-only growth). |
| Relationship Reinforcement | `pipeline/RelationshipReinforcer.kt` | Only stage that adds the EVIDENCE edge type (evidence must exist first) and writes the `MemoryRecord`. |
| Render Updated Neural Landscape | `pipeline/RuntimeSnapshotBuilder.kt` | Builds the one object the UI may read: nodes with activation decayed to "now", full edge set, pulse frequency derived from nodes active in the last 60s. |

### Data model (`core/model/`)

`NodeType` (10 domains) × `EdgeType` (7 relationship kinds) graph; `Event` →
`NormalizedEvent` → `Classification`; `GraphNode` / `GraphEdge`;
`MemoryRecord` (always carries `evidenceId`); `EvidenceRecord`;
`GovernanceDecision` (`GovernanceViolation.blocking: Boolean`);
`CommercialAssessment`; `ExecutionOutcome`; `AuditTrailEntry`; `PipelineResult`
(the full per-event record); `SyncQueueItem`; `RuntimeSnapshot` /
`RenderedNode` (the visualization's only legal data source).

### Storage seam (`core/repository/` interfaces, two implementations)

```
GraphRepository, MemoryRepository, EvidenceRepository,
AuditTrailRepository, SyncQueueRepository
```

- `core/repository/InMemoryRepositories.kt` — `ConcurrentHashMap`-backed,
  used by all unit tests.
- `app/data/repository/RoomRepositories.kt` — Room-backed, used by the
  Android app. Mapping functions (`NodeEntity.toModel()` etc.) are
  `internal` top-level extensions so the reactive Compose ViewModels
  (`NeuralLandscapeViewModel`) can reuse them instead of re-deriving mapping
  logic.

### Android app layer (`app/`, unverified — see CLAUDE.md)

- `AppDatabase` (Room, version 1): `nodes`, `edges`, `event_node_bindings`,
  `memories`, `evidence`, `audit_trail`, `sync_queue` tables.
- `SubstrateApplication` — manual DI (no Hilt/Koin; object graph is five
  repositories + one `EventPipeline`).
- Three Compose screens under one `MainActivity` + bottom nav:
  - **Capture** (`ui/capture/`) — the only input surface. Submits through
    `EventPipeline.submit()` on `Dispatchers.IO`, shows classification,
    governance verdict, execution outcome, and the full audit trail for that
    event.
  - **Landscape** (`ui/landscape/`) — Canvas visualization. Reactive: Room
    `Flow<List<NodeEntity>>` / `Flow<List<EdgeEntity>>` combined with a 500ms
    clock tick, decay computed via the *same* `ActivationPulseGenerator` used
    server-side (no duplicated math). Node color = domain (`NodeType`),
    brightness = decayed activation, radius = importance, edge thickness =
    weight, edge alpha = recency (fades over 5 min), pulse animation period =
    `1200ms / activityPulseFrequencyHz` (faster pulse when more nodes fired
    in the last minute — not a fixed decorative constant). Layout is a
    **deterministic radial placement** (one 36° sector per domain, radius
    inversely proportional to importance) — explicitly not a force-directed
    physics simulation; documented as a known simplification in CLAUDE.md.
  - **Audit** (`ui/audit/`) — most recent 200 audit entries, live via Room
    `Flow`.

### Build/verification status

- `core`: **built and tested for real** in this sandbox (JDK 21, system
  Gradle 8.14.3, no Android SDK needed). 16 tests, all green as of this
  build. Run `gradle :core:test` from `substrate-runtime/` to reproduce.
- `app`: **not compiled, not run**. No Android SDK/emulator in this sandbox.
  Needs Android Studio or an SDK-equipped CI runner. Treat as reviewed
  source, not verified source, until that happens.

### What is explicitly NOT implemented (do not assume it exists)

- No sync transport (`SyncQueueRepository` fills a local queue; nothing
  drains it).
- No external AI/LLM call anywhere — classification and scoring are
  deterministic heuristics.
- No topic/concept clustering across differently-worded but related events
  (only exact-text-repeat or shared explicit tag consolidates a node).
- No force-directed graph layout (deterministic radial placement instead).
- No `FORGE.REQUEST_BUILD` / `REQUEST_REVIEW` / `EXPORT` integration between
  this new module and the original bash scaffold in §1 — the two systems are
  not wired together.
