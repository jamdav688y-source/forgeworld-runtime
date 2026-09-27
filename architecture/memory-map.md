# ForgeWorld Memory Map

See `gap-matrix.md` #1 for classification (`PARTIAL`).

## Real, durable, code-backed memory (narrow domains only)

| Store | File | Durability mechanism | Test evidence |
|---|---|---|---|
| Artifact lineage | `artifact_handoff/lineage_store.py::LineageStore` | `evidence_envelope`'s `_FileLock` + `_atomic_write_bytes`, JSONL, idempotent-duplicate / conflict-on-mismatch | 12/12 passing |
| Mission evidence | `evidence_envelope/envelope.py::EnvelopeStore` | Same primitives, BRONZE→SILVER→GOLD lifecycle | Native suite unrunnable here (no pytest); exercised transitively via lineage_store |
| Run/trajectory comparison | `evidence_envelope/trajectory.py::TrajectoryStore` | Same primitives, append-only run records | Native suite unrunnable here |
| Capability routing history | `capabilities/history.jsonl`, `router/decisions.jsonl` | Plain append — **no lock, no atomicity** | No dedicated test suite for the log files themselves |

All four use JSONL as the on-disk shape. Only the first three go through
the durability primitives (`_FileLock`/`_atomic_write_bytes`); the routing
logs are a weaker, older, pre-durability-discipline mechanism (explicitly
called out as such in `evidence_envelope/trajectory.py`'s own docstring:
*"router/decisions.jsonl and capabilities/history.jsonl are a separate,
older, simpler concept... explicitly untouched operational ledgers"*).

## Non-durable, in-memory-only "memory"

`fabric/interface.py::FabricArtifactIndex` — cross-node artifact-identity
dedup, in-memory dict only, explicitly documented as a bounded limitation
("a durable version would reuse envelope.py's _FileLock/_atomic_write_bytes
exactly as lineage_store.py already does, deferred").

## Stale, non-code memory

`memory/memory.log`, `memory/memory.md`, `memory/memory_writer.txt` (root)
— three text files, no reader, no writer, no schema. Predates the code-
backed substrate; not wired to anything.

## What no memory type has, anywhere

- A `memory_type` taxonomy (episodic/semantic/project/relationship/
  commercial/decision/evidence/capability/procedural/working) — every
  existing store is single-purpose and untyped in this sense.
- A `promotion_state`/`verification_state` pair distinguishing "observed"
  from "verified" from "durable truth" at the memory-object level (the
  fixed-property pattern exists on *result* objects like `Manifest`, not
  on any persisted memory record).
- A `ContextCompiler`-equivalent: nothing selects "the smallest relevant
  memory for this objective" — there is no query surface across these four
  stores at all, let alone a compiled one.
- `supersedes`/`contradicts`/`derived_from` relationships between memory
  records — none of the four stores model this.

## Direct implication for Section 8 of the mission brief

Building PermanentMemory as specified is **not starting from zero**: the
durability primitives (`_FileLock`, `_atomic_write_bytes`,
`validate_mission_id`, `LedgerIntegrityError`) are proven, reused three
times already, and directly reusable a fourth time for whatever the
eventual PermanentMemory store's on-disk mechanism turns out to be. The
gap is entirely at the schema/taxonomy/query layer, not the durability
layer.
