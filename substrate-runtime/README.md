# substrate-runtime — MICRO_SUBSTRATE_RUNTIME_V1

Native Android (Kotlin) implementation of the FORGEWORLD cognitive substrate runtime:
every user interaction is captured as an event, pushed through a governed 12-stage
pipeline, and projected as a live "neural landscape" graph visualization that is a
direct readout of runtime state — not a decorative UI.

## Modules

- **`core`** — pure Kotlin/JVM, zero Android dependency. Contains the domain model,
  the full event pipeline (capture → normalize → classify → activation pulse →
  memory retrieval → relationship expansion → governance validation → commercial
  opportunity analysis → execution decision → evidence recording → relationship
  reinforcement → runtime snapshot), repository interfaces, and in-memory
  reference implementations. Fully buildable and testable with a plain JDK —
  no Android SDK required.
- **`app`** — Android application module. Room persistence implementing the
  `core` repository interfaces, and a Jetpack Compose UI (capture screen,
  neural landscape visualization, audit trail inspector).

## Build status in this environment

This sandbox has JDK 21 and Gradle 8.14.3 but **no Android SDK**. That means:

- `gradle :core:test` builds and runs for real here — the pipeline logic
  (classifier, vector index, governance validator, commercial analyzer,
  activation decay, graph engine) is genuinely exercised and verified.
- `:app` (Room + Compose + AGP) **cannot be compiled or run in this sandbox**.
  It needs to be opened in Android Studio (or built in a CI runner with the
  Android SDK installed) to compile, install, and be visually verified on a
  device/emulator. Treat `:app` as reviewed-but-unverified until that happens.

## Governing invariants

See `docs/MICRO_SUBSTRATE_RUNTIME_V1.md` in the repo root doctrine set (and
`ARCHITECTURE_INDEX.md`) for the full specification this module implements.
