# CLAUDE.md — orientation for working in this repository

This file is the entry point. Read it before touching anything. It points to
four companion documents that together are this repository's permanent
architectural memory:

- **ARCHITECTURE_INDEX.md** — the full system map: every layer, module, and
  how they connect (both the original FORGEWORLD doctrine/bash scaffold and
  the new `substrate-runtime/` Android application).
- **ENGINEERING_MEMORY.md** — decisions made and why, bugs found and fixed,
  things tried and rejected. Read this before re-deriving a design choice
  that's already been made.
- **PATTERN_LIBRARY.md** — the conventions established in `substrate-runtime/`
  (id schemes, repository/fake/Room pattern, audit logging, etc.). Follow
  these when extending the codebase instead of inventing new ones.
- **MISSION_LOG.md** — chronological record of what was asked for and
  delivered, mission by mission.

## What this repository is, as of 2026-07-03

Two things coexist here:

1. **The original FORGEWORLD doctrine/bash scaffold** (repo root: `governance/`,
   `doctrine/`, `events/`, `memory/`, `scripts/`, etc.) — a personal,
   human-operated continuity/governance system for a phone-and-laptop workflow.
   It is prose doctrine plus ~16 small Bash scripts with no automated
   enforcement, no tests, and hardcoded `$HOME/forgeworld` paths that do not
   match this checkout. See ARCHITECTURE_INDEX.md §1 for the full survey.

2. **`substrate-runtime/`** — a real, working, native Android (Kotlin)
   implementation of `MICRO_SUBSTRATE_RUNTIME_V1`: a governed event pipeline
   that is the first piece of *code* in this repository's history to actually
   enforce the governance doctrine described in `governance/CONSTITUTION_v3.txt`
   rather than merely echo it into a log file. See ARCHITECTURE_INDEX.md §2.

These two are intentionally not merged. The bash scaffold is left as-is
(no destructive changes were made to it during discovery or this build).

## Working in `substrate-runtime/`

```
cd substrate-runtime
gradle :core:test        # builds and tests for real — no Android SDK needed
```

- `core/` is pure Kotlin/JVM (zero Android dependency). All pipeline logic
  lives here and is unit-tested. This is where you should make changes to
  classification rules, governance checks, graph/edge logic, or scoring
  heuristics — then run `gradle :core:test` to verify.
- `app/` is the Android application module (Room + Jetpack Compose). **This
  sandbox has no Android SDK**, so `:app` has never been compiled or run here
  — it is reviewed-quality code, not verified-quality code. Anyone continuing
  this work needs Android Studio (or a CI runner with the SDK) to build,
  install, and visually check `:app` before trusting it further.
- Every pipeline stage writes an audit trail entry
  (`substrate.core.model.AuditTrailEntry`). If you add a stage, add its log
  line — the Observability requirement in the mission spec is structural,
  not optional, and tests check `auditTrail.size >= 12`.

## Ground rules carried over from governance doctrine

These are enforced in code now (`substrate.core.pipeline.GovernanceValidator`),
not just written in `governance/CONSTITUTION_v3.txt`:

- No blank actor (`ACCOUNTABLE_ACTOR`).
- No self-referential event dependencies (`NO_SELF_DEPENDENCY`).
- No empty event content (`NON_EMPTY_CONTENT`).
- Low-confidence classification holds for review rather than silently
  executing (`CLASSIFICATION_CONFIDENCE_BELOW_THRESHOLD`).
- Evidence is deduplicated per event id, never re-created
  (`REUSE_EXISTING_EVIDENCE`).

If you add a new governance rule, add it there, add a test in
`GovernanceValidatorTest.kt`, and record the reasoning in
ENGINEERING_MEMORY.md.

## Known limitations — do not silently "fix" without discussion

These are documented tradeoffs, not oversights. See ENGINEERING_MEMORY.md for
the reasoning behind each:

- `VectorIndex` is bag-of-words term-frequency + cosine similarity with a
  small fixed stopword list — not full TF-IDF (no corpus-wide document
  frequency).
- Topic-node consolidation is text-literal (deterministic slug of the
  cleaned text or first tag) — two *different* sentences about the same
  subject will not automatically merge into one node. Only identical
  repeated text, or a shared explicit tag (`#project:x`), consolidates.
- No sync transport is wired up. `SyncQueueRepository` is a real local
  queue; nothing drains it yet.
- No external AI/LLM integration exists anywhere in this repository. The
  classifier and scorers are deterministic keyword/heuristic logic, not
  model calls — this was a deliberate scope decision (see MISSION_LOG.md),
  not a stub waiting to be filled by an API key.
