# Continuity Substrate Ascension V1

Phone-side cognitive substrate upgrade, built as an incremental extension of
the substrate created in the prior session (`substrate/README.md`,
`substrate/schema/mission.schema.json`, the registries, and
`process-queue.sh`/`new-mission.sh`/`update-mission.sh`/`validate-mission.sh`).
Nothing from that layer was replaced, redesigned, or duplicated — this
document describes what was added around it and how the two fit together.

## Primary objective and Primary Law

The phone is now able to record a fully schema-validated, governance-tagged
observation offline (`scripts/sensor-capture.sh`) instead of only a free-text
queue line. Every such capture is checked against the Primary Law before it
counts as done: it must carry evidence, a governance classification, a
commercial-potential judgment (even if "unknown"), and — as of this
iteration — a non-empty `suggested_next_action`. `validate-schema.sh` and
`governance-check.sh` enforce this mechanically rather than by convention.

## Module map

| Module | What it is | Where it lives |
|---|---|---|
| 01 Local Mission Capture Engine | Phone sensor mission schema + capture script | `mission_schema.json`, `scripts/sensor-capture.sh`, `missions_phone/*.json` |
| 02 Offline Event Journal | Immutable, hash-deduplicated append log | `event_journal.jsonl`, `journal_append()` in `scripts/lib.sh` |
| 03 Evidence Package Engine | Assembles a portable, hashed evidence bundle around a mission | `evidence_package_schema.json`, `scripts/build-evidence-package.sh`, `evidence_packages/*.json` |
| 04 Capability Genome | Registry of reusable capabilities, upserted per completed mission | `capability_genome.json`, `scripts/update-capability-genome.sh` |
| 05 Phone -> Desktop Synchronization | Deterministic, read-only export manifest | `scripts/export-desktop-packet.sh`, `sync/desktop_export_manifest.json` |
| 06/07 Continuity + Knowledge Graph | Rebuildable graph derived from missions/registries/capabilities, plus manual entities (people/topics/concepts/...) | `relationship_graph.json`, `scripts/update-relationship-graph.sh` |
| 08 Runtime Governance | Read-only report of governance/confidence/integrity/approval fields | `scripts/governance-check.sh` |
| 09 Instrumentation | Real metrics computed from disk, snapshotted over time | `instrumentation_history.jsonl`, `scripts/instrumentation.sh` |
| 10 Operator Console | Extended `substrate-status.sh` (not a second console) | `scripts/substrate-status.sh` |
| 11 Claude Participation Rule | Policy, not code — see below | this document |

A phone sensor mission (PSM-...) is joined to the existing desktop mission
pipeline (MSN-...) by `scripts/promote-sensor-mission.sh`, which reuses
`new-mission.sh` exactly the way `process-queue.sh` already promotes
`capture/queue.jsonl` entries. There is one continuity system, not a phone
system and a laptop system that happen to share a folder.

## Design decisions made to satisfy the implementation constraints

- **No cloud dependency, no new runtime dependency.** Everything is bash +
  `jq` + `sha256sum`, all already required by the substrate built last
  session. `validate-schema.sh` deliberately does *not* pull in a
  `jsonschema` package — it checks required-field presence, which is the
  actual failure mode this substrate needs to catch, not full JSON Schema
  semantics.
- **Deterministic export.** `export-desktop-packet.sh` is read-only: earlier
  drafts rebuilt the relationship graph and logged their own run to the
  event journal before hashing it, which meant the export mutated the very
  files it was about to hash. Fixed by making export a pure report over
  whatever state already exists; rebuilding the graph is now a separate,
  explicit step.
- **Reversibility.** Every new data file (`mission_schema.json`,
  `event_journal.jsonl`, `evidence_package_schema.json`,
  `capability_genome.json`, `relationship_graph.json`,
  `sync/desktop_export_manifest.json`) is additive. Deleting the whole
  `substrate/` ascension additions (everything except last session's
  `schema/`, `registries/`, `missions/`, `capture/`, and the six original
  scripts) leaves the prior substrate exactly as it was, and deleting
  nothing at all is also always safe — no in-place migration of existing
  files was performed.
- **Namespacing to avoid ID collisions.** Phone sensor missions use a
  `PSM-` prefix, distinct from the desktop `MSN-` prefix, so the two mission
  populations can be merged, cross-referenced, and promoted without ever
  colliding.

## Module 11: Claude Participation Rule

Claude does not own continuity. On every invocation, Claude receives a
mission packet (a PSM or MSN mission plus whatever evidence/knowledge is
linked to it) and returns artifacts, analysis, reports, code, validation, or
recommendations — written back through `update-mission.sh`,
`build-evidence-package.sh`, `update-capability-genome.sh`, etc. ForgeWorld
itself — the files in this repository — owns identity, memory, governance,
knowledge, lineage, capability, and evolution. Claude is replaceable; the
substrate is not. Nothing in this ascension layer calls out to a specific
model provider by name, for the same reason last session's `ARCHITECTURE.md`
gives: any reasoning engine can read a mission and write results back.

## Evolution beyond this: Substrate Reflection Engine (recommended next iteration)

Not built in this pass, and deliberately scoped out rather than built
half-way: a **Substrate Reflection Engine** that periodically reads the
accumulated mission graph, capability genome, and instrumentation history
and answers questions the current tooling can only be asked one at a time
by hand —

- Which capabilities are compounding fastest (`reuse_frequency` growth rate
  in `capability_genome.json` over successive `instrumentation_history.jsonl`
  snapshots)?
- Which missions repeatedly produce high-value reusable assets (join
  `asset_registry.json` and `commercial_registry.json` on `mission_id`,
  rank by count and `commercial_value`)?
- Where are the largest knowledge gaps (nodes in `relationship_graph.json`
  with low edge density, or capabilities with no `knowledge_domains`
  overlap to existing missions)?
- Which improvements would unlock the most future capability across the
  whole system (capabilities with high `strengthens` fan-out but low
  `reuse_frequency` — underused leverage points)?

This shifts the substrate from accumulating information to directing its
own evolution against measurable long-term leverage, exactly as described
in the directive's closing note. It was not built now because Module 09
(Instrumentation) needs at least a few real snapshots over time before a
trend-detection engine has anything to detect — building it against a
single data point would produce fabricated-looking "insights" rather than
real ones. Recommended trigger: revisit once `instrumentation_history.jsonl`
has snapshots spanning several real missions across at least a few days of
actual use.
