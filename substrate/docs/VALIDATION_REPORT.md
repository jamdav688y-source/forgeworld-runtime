# Validation Report — Continuity Substrate Ascension V1

All checks below were actually executed against this repository in this
session (not simulated). Commands are given so any of them can be re-run.

| # | Requirement | Method | Result |
|---|---|---|---|
| 1 | Mission creation | `sensor-capture.sh --objective ... --observation ...` created `PSM-20260703T215640Z-1840` | PASS |
| 2 | Offline persistence | Capture and journal write are local file operations only; no network call anywhere in `sensor-capture.sh`, `capture-idea.sh`, or `journal_append()` | PASS (verified by code inspection — no `curl`/`wget`/network calls exist in any substrate script) |
| 3 | Relationship creation | `promote-sensor-mission.sh PSM-20260703T215640Z-1840` created bidirectional links (`related_missions` on the PSM, `source_context.capture_id` + evidence on the MSN); `update-relationship-graph.sh rebuild` produced 13 nodes / 17 edges including a `promoted_to` edge | PASS |
| 4 | Capability updates | `update-capability-genome.sh upsert phone-native-structured-capture` run twice; second run merged `produces` (deduplicated), incremented `reuse_frequency` 1 -> 2, and appended to `contributing_missions` without discarding the first run's data | PASS |
| 5 | Knowledge linking | `update-relationship-graph.sh rebuild` derives `*_of_mission` edges from every registry (`knowledge`, `evidence`, `decision`, `prompt`, `workflow`, `commercial`, `asset`) plus `evidence_package_of_mission` and `strengthened_by_mission`/`strengthens`/`produces` edges from the capability genome | PASS |
| 6 | Synchronization packet generation | `export-desktop-packet.sh` wrote `sync/desktop_export_manifest.json` listing 15 files across missions, phone sensor missions, evidence packages, registries, capability genome, relationship graph, and event journal, each with a sha256 | PASS |
| 7 | Recovery after restart | Ran `substrate-status.sh` inside `env -i` (empty environment, fresh shell, no inherited state) — produced identical, correct output because all state lives in files, not process/session memory | PASS |
| 8 | Schema validation | `validate-schema.sh mission_schema.json <PSM file>` and `validate-schema.sh evidence_package_schema.json <EVP file>` both PASS on valid instances; a deliberately truncated test document correctly FAILed and listed every missing required field | PASS |
| 9 | Duplicate detection | Re-ran `sensor-capture.sh` with byte-identical `--objective`/`--observation`/`--context` — correctly reported `DUPLICATE of PSM-...` and did not create a second file; `journal_append()`'s hash check independently prevents duplicate journal lines for identical `(event_type, source, payload)` triples | PASS |
| 10 | Deterministic export | Ran `export-desktop-packet.sh` twice in a row with no substrate changes between runs; diffed both manifests with `generated_at` stripped — byte-identical, including the `packet_integrity_hash`. (An earlier draft failed this: it rebuilt the relationship graph and journaled its own run *before* hashing, so the second run's hash never matched the first. Fixed by making the export script read-only.) | PASS (after one fix — see `CONTINUITY_ASCENSION.md`) |
| 11 | Zero destructive migration | `git diff --stat HEAD -- doctrine governance memory world rpg factions` is empty; no existing file under `substrate/schema/`, `substrate/registries/`, `substrate/missions/`, `substrate/capture/`, or the six pre-ascension scripts was modified, only new files were added alongside them | PASS |

## Bugs found and fixed during this validation pass

These are listed because catching them *is* the point of running real
validation instead of asserting success:

1. **Empty-array bug in `update-capability-genome.sh`.** Bash's
   `"${arr[@]:-}"` expansion on an empty array under `set -u` produces one
   stray empty-string element, so an omitted `--dependency`/`--strengthens`/
   etc. flag was serializing to `[""]` instead of `[]`. Fixed by filtering
   empty strings in `to_json_arr` and in the jq `dedup` helper. Verified by
   re-running the upsert twice and inspecting the output.
2. **Non-deterministic export.** Described above — `export-desktop-packet.sh`
   was mutating (rebuilding the graph, journaling its own run) before
   hashing the very files it reported on. Fixed by removing both
   side-effects from the export path.
3. **Missing `suggested_next_action` default.** `sensor-capture.sh` left
   `suggested_next_action` blank unless the operator supplied `--next-action`,
   which fails both `mission_schema.json`'s required-field list and the
   Primary Law ("every interaction must permanently increase reusable
   organizational capability" implies every capture points somewhere next).
   Fixed with a sensible default plus an explicit override flag; caught by
   running `validate-schema.sh` against a real captured instance, not by
   reading the code.
4. **Operator-precedence bug in `governance-check.sh`.** `A || B && C` in
   bash evaluates as `A || (B && C)`, so when `validation_status` actually
   was `"validated"`, the branch that should have set
   `operator_approval_required="no"` never ran. Fixed with an explicit `if`.

## Known gaps (not fixed, scoped out honestly rather than papered over)

- `governance-check.sh`'s `risk_score` is always reported as `"unknown"` —
  no risk-scoring model exists yet. It is surfaced as explicitly unknown
  (per Module 08: "unknown information remains explicitly marked as
  unknown") rather than a fabricated number.
- The Substrate Reflection Engine described in the directive's closing note
  was intentionally not built this pass — see `CONTINUITY_ASCENSION.md` for
  why and what would trigger building it.
- No native phone camera/microphone/OCR/clipboard integration exists;
  `sensor-capture.sh`'s `evidence_type` values (`photo`, `screenshot`,
  `voice_note`, etc.) describe what the operator is recording, not an
  automated capture pipeline. That requires actual mobile app plumbing
  beyond a shell+jq substrate.
