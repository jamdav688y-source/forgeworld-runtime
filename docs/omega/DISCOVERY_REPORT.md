# FW-SCS-001 Stage A — Repository Discovery Report

Inspected: 2026-11-10 · repository `forgeworld-runtime` · branch `ccr-0aad6294-t51qv4`
· base commit `26d2ec2c936e32bb7f789e3ff072aaf1ec4d8e4c` (merge of PR #11)

## Where the inspection ran — and what it could not see

The inspection ran in a **Linux cloud container** (Python 3.13.18, SQLite 3.53.1 with FTS5,
`cryptography` 50.0.1). It did **not** run on the Windows PC or on Android/Termux, and
Ollama is **not installed** here. Anything about those environments is classified from the
code alone and is marked accordingly. The directive says "Inspect the Windows repository": the
Windows checkout itself is not reachable from this session, so this report covers the GitHub
branch only.

Several components the directive names are **referenced in the code but absent from this
branch**: `cognition/cycle.py:160` records `"CapabilityPromotionGate (substrate/) is not on this
branch"`, and `cognition/cxp.py` / `exchange.py` say they import nothing from `fabric/` or
`substrate/`. `fabric/tests/test_receiver_authorization.py` is cited as evidence at commit
`15a56f7…`, which this branch does not contain. They are probably on the Windows working copy
or an unmerged branch. They are classified **MISSING (on this branch)**, not BLOCKED: nothing
prevents merging them, they just are not here.

## Baseline test run (re-run, not trusted from earlier reports)

| Suite | Runner | Result |
|---|---|---|
| `cognition/tests` | `python -m unittest discover -s cognition/tests -t .` | **388 passed** |
| `evidence_envelope/tests` | `pytest` | **91 passed** |
| `capabilities/tests` | `pytest` | **13 passed, 2 skipped** (Windows-only Store-alias cases) |
| `forgeworld-mobile-research/tests` | `pytest` | **13 passed** |

`pytest` was not installed in the container at first; it was installed with pip for the run.

## Component classification

The machine-readable version is [`capability_inventory.json`](capability_inventory.json).

| Directive component | Found | Status |
|---|---|---|
| CapabilityGraph | referenced nowhere as code | **MISSING** |
| WorkflowCompiler | referenced nowhere as code | **MISSING** |
| CapabilityPromotionGate | `substrate/` — "not on this branch" | **MISSING (on this branch)** |
| Governance / authorization | `cognition/cxp.py` (authority fields forbidden), `cognition/governor.py` (recursion governor), `evidence_envelope/envelope.py` (verified promotion-authority attestations) | **VERIFIED** |
| Identity and device pairing | none | **MISSING** → now `omega/identity.py` |
| Replay protection | `cognition/exchange.py` (DUPLICATE_OCCURRENCE / DUPLICATE_RECORD, erase-aware) — in-store only, no transport | **VERIFIED (store level)**; transport replay was MISSING → `omega/sync.py` |
| Evidence receipts | `cognition/exchange.py` IngestReceipt; envelope ledger | **VERIFIED** |
| Memory / persistence | `forgeworld-mobile-research/database.py` (SQLite + FTS5), envelope/trajectory ledgers | **VERIFIED** |
| Narrative logs (`events/`, `memory/`, `world/`, `npc/` …) | text files; no code reads or writes them (as `trajectory.py` also notes) | **PRESENT BUT UNTESTED** (left untouched) |
| Phone-to-PC transport | `scripts/forge-sync-pack.sh` (tar.gz; no authentication, no encryption, no import side) | **PARTIAL** |
| Mission router | `router/mission_router.py` (exercised indirectly by `cognition/tests/test_odcc.py`) | **PRESENT, indirectly tested** |
| Capability discovery | `capabilities/discover.py` | **VERIFIED** |
| Ollama configuration | registry entry `local_llm` (`check: command ollama`); binary absent here | **BLOCKED in this environment** |
| Test fixtures / regression harness | `cognition/tests/_events.py`, `_commerce_events.py`, envelope fixtures | **VERIFIED** |

## Decisions taken from the discovery

1. **New package `omega/`, not `substrate/`.** A `substrate/` package exists elsewhere (Windows
   side); creating one here would collide with it on merge (ADR-0001).
2. **Reuse, don't replace.** `omega/canonical.py` reuses `cognition.cxp.canonical_bytes`;
   `omega/diagnostics.py` follows `docs/architecture/MISSION_CONTROL_DATA_CONTRACT.md`;
   `omega/commercial.py` keeps the same distinctions as `cognition/commerce.py` without changing
   it (ADR-0003). No existing module was modified.
3. **Untouched:** every existing module, ledger (`capabilities/history.jsonl`,
   `router/decisions.jsonl`) and narrative file.
