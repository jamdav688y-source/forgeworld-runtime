# ForgeWorld Current State

Recovery snapshot for MISSION_ID: FORGEWORLD-CONTINUITY-FABRIC-001, Phase 0.
Generated from repository evidence only. No claim below is asserted without
a cited file and, where applicable, a passing test count observed in this
session. See `evidence/recovery-receipt.json` for the machine-readable form.

**Repository identity:** `jamdav688y-source/forgeworld-runtime`, branch
`claude/eager-mayer-n45ddd`, HEAD `6e00f0b0f47f3515cf1080ee59938c6f3f35765c`,
worktree dirty (`fabric/loopback/wire.py` modified, `fabric/tcp/` untracked),
branch ahead of `origin` by 1 unpushed commit.

## Two layers coexist in this repository

**Layer 1 — narrative scaffolding (pre-existing, inert).** `governance/`,
`doctrine/`, `commands/`, `memory/`, `npc/`, `npcs/`, `quests/`,
`relationships/`, `reputation/`, `events/`, `consequences/`, `future/`,
`inbox/`, `notes/`, `diagnostics/`, `council_reviews/`, `factions/`, `rpg/`,
`world/`, `logs/`, `tasks/`, plus root `README.md`/`README.txt`/`STATUS.md`/
`TASKS.md`/`CAPTURE.md`/`world_state.json` and the `install_*.sh` /
`log_event.sh` / `resolve_event.sh` / `runtime.sh` shell scripts. **No code
anywhere in this repository reads or writes these paths** (confirmed
originally when `trajectory.py` was written, and unchanged since). They are
text artifacts from an earlier RPG/persistence-framing attempt at some of
the same concepts this mission's target architecture names (memory, events,
relationships, reputation) — STALE, not DUPLICATE, because nothing competes
with them at runtime.

**Layer 2 — real, tested, code-backed substrate (built this program).**
Nine Python packages, each with its own bounded `unittest` suite, all
package-qualified (no bare-module-name collisions), all reusing a small set
of shared primitives rather than reinventing them:

| Package | Role |
|---|---|
| `capabilities/` | Capability registry (`registry.json`) + reachability probing (`discover.py`) |
| `router/` | Deterministic capability scoring/selection (`mission_router.py`) |
| `evidence_envelope/` | Mission lifecycle ledger (BRONZE→SILVER→GOLD), atomic-write/file-lock primitives, mission-trajectory comparison |
| `local_inference/` | Provider-neutral local-model invocation contract; Ollama is one adapter |
| `content_readers/` | Provider-neutral content-reading contract (text/JSON/YAML/CSV/HTML/source/image-metadata/archive-inventory) |
| `artifact_handoff/` | Artifact acquire→classify→safe-unpack→route pipeline; durable lineage store |
| `fabric/` | Two-node (PC_NODE/PHONE_NODE) contract: identity, authority, envelopes, transfer, remote capability requests, deterministic receipts; loopback (same-machine process boundary) and TCP (real network) transport adapters |
| `forgeworld-mobile-research/` | Standalone Flask app: phone-side screenshot capture, OCR, classification, FTS5 search — **never wired to `fabric/`** |
| `tests/` (root) | Cross-package integration proof (namespace stabilization) |

Full regression, re-run fresh in this session immediately before writing
this document: **146/146 tests passing**, 0 failures, across
`capabilities` (14), `local_inference` (18), `artifact_handoff` (21),
`artifact_handoff` lineage (12), `content_readers` (25),
`tests/test_namespace_stabilization.py` (8), `fabric` contract (19),
`fabric` loopback (17), `fabric` TCP (12). No orphan processes, no leaked
temp resources, no writes to `capabilities/state.json` or
`router/decisions.jsonl` from running them.

**Known execution gaps in THIS sandbox** (not defects in the code): no
`pytest` installed, so `capabilities/tests/test_discover.py`,
`evidence_envelope/tests/test_envelope.py`,
`evidence_envelope/tests/test_trajectory.py`, and all of
`forgeworld-mobile-research/tests/` cannot be executed here and are
classified `PRESENT_UNVERIFIED` rather than `PROVEN_WORKING`, regardless of
what their own prior validation reports claim.

## What is physically proven vs. simulated

- A raw TCP packet (`nc`) crossed a real Android (Termux) → Windows network
  boundary, and a reply crossed back — demonstrated by the operator, outside
  any ForgeWorld code.
- The ForgeWorld fabric contract itself has been proven only: (a) in-memory,
  single-process; (b) across a real OS process boundary on this Linux
  sandbox via Unix-domain-socket loopback; (c) across a real TCP/AF_INET
  socket, also loopback-bound, in this sandbox. **No governed ForgeWorld
  fabric message has yet crossed the physical phone↔PC boundary.**
- The TCP fabric code does not yet exist in the physical Windows checkout
  at all (`Test-Path` there returned `False` for `fabric/tcp/*` as of the
  last reconciliation mission) — a manual archive-based reconciliation
  procedure was produced and delivered to the operator but completion is
  unconfirmed.

See `architecture/gap-matrix.md` for the primitive-by-primitive
classification and `architecture/target-state.md` for what Section 3 of
this mission's brief asks for next.
