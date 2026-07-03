#!/usr/bin/env bash
# Shared helpers for the ForgeWorld continuity substrate.
# Sourced by every substrate script. Portable bash + jq: works on laptop
# and on phone (Termux) as long as `jq` is installed (`pkg install jq`).

set -euo pipefail

SUBSTRATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$SUBSTRATE_DIR/.." && pwd)"
REGISTRY_DIR="$SUBSTRATE_DIR/registries"
MISSIONS_DIR="$SUBSTRATE_DIR/missions"
CAPTURE_DIR="$SUBSTRATE_DIR/capture"
SCHEMA_DIR="$SUBSTRATE_DIR/schema"
QUEUE_FILE="$CAPTURE_DIR/queue.jsonl"

# CONTINUITY_SUBSTRATE_ASCENSION_V1 additions (Modules 01-10). These extend
# the same substrate created above; nothing above this line changes shape.
PHONE_MISSIONS_DIR="$SUBSTRATE_DIR/missions_phone"
EVIDENCE_PACKAGES_DIR="$SUBSTRATE_DIR/evidence_packages"
EVENT_JOURNAL="$SUBSTRATE_DIR/event_journal.jsonl"
CAPABILITY_GENOME="$SUBSTRATE_DIR/capability_genome.json"
RELATIONSHIP_GRAPH="$SUBSTRATE_DIR/relationship_graph.json"
INSTRUMENTATION_HISTORY="$SUBSTRATE_DIR/instrumentation_history.jsonl"
SYNC_DIR="$REPO_ROOT/sync"
EXPORT_MANIFEST="$SYNC_DIR/desktop_export_manifest.json"

require_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required. Install it (e.g. 'pkg install jq' on Termux, 'apt install jq' on laptop)." >&2
    exit 1
  fi
}

now_iso() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

gen_id() {
  # gen_id PREFIX -> PREFIX-20260703T214500Z-1234
  local prefix="$1"
  printf '%s-%s-%04d\n' "$prefix" "$(date -u +%Y%m%dT%H%M%SZ)" "$((RANDOM % 10000))"
}

registry_path() {
  echo "$REGISTRY_DIR/${1}_registry.json"
}

# --- Ascension helpers (hashing, immutable journal, schema field check) ---

sha256_str() {
  printf '%s' "$1" | sha256sum | cut -d' ' -f1
}

sha256_file() {
  sha256sum "$1" | cut -d' ' -f1
}

# require_field JSON_FILE FIELD_PATH -> prints "unknown" instead of null/empty
# so governance fields are never silently blank (Module 08).
field_or_unknown() {
  local file="$1" path="$2"
  local val
  val="$(jq -r "$path // \"unknown\"" "$file" 2>/dev/null || echo unknown)"
  [ -z "$val" ] && val="unknown"
  echo "$val"
}

# journal_append EVENT_TYPE SOURCE PAYLOAD_JSON [MISSION_ID ...]
# Appends one immutable line to event_journal.jsonl. Detects exact-content
# duplicates by hash and returns the existing event_id instead of
# re-appending (set FORCE_DUPLICATE=1 to append anyway). Never rewrites or
# deletes existing lines - append-only.
journal_append() {
  local event_type="$1" source_forge="$2" payload_json="$3"
  shift 3
  local mission_assoc_json="[]"
  if [ "$#" -gt 0 ]; then
    mission_assoc_json="$(printf '%s\n' "$@" | jq -R . | jq -sc .)"
  fi
  mkdir -p "$SUBSTRATE_DIR"
  touch "$EVENT_JOURNAL"

  local canon hash existing
  canon="$(jq -Sc -n --arg t "$event_type" --arg s "$source_forge" --argjson p "$payload_json" \
    '{event_type:$t, source:$s, payload:$p}')"
  hash="$(sha256_str "$canon")"

  existing="$(jq -c --arg h "$hash" 'select(.hash == $h)' "$EVENT_JOURNAL" 2>/dev/null | head -1 || true)"
  if [ -n "$existing" ] && [ "${FORCE_DUPLICATE:-0}" != "1" ]; then
    echo "DUPLICATE_OF $(echo "$existing" | jq -r '.event_id')" >&2
    echo "$existing" | jq -r '.event_id'
    return 0
  fi

  local event_id ts
  event_id="$(gen_id EVT)"
  ts="$(now_iso)"
  jq -nc \
    --arg event_id "$event_id" \
    --arg ts "$ts" \
    --arg event_type "$event_type" \
    --arg source "$source_forge" \
    --arg hash "$hash" \
    --argjson mission_association "$mission_assoc_json" \
    --argjson payload "$payload_json" \
    '{event_id:$event_id, timestamp:$ts, event_type:$event_type, source:$source, hash:$hash,
      mission_association:$mission_association, governance_classification:"unclassified",
      confidence:"unknown", lineage:[], payload:$payload}' \
    >> "$EVENT_JOURNAL"
  echo "$event_id"
}

# append_registry_entry REGISTRY_NAME JSON_ENTRY
append_registry_entry() {
  local reg_name="$1" entry_json="$2"
  local path
  path="$(registry_path "$reg_name")"
  local tmp
  tmp="$(mktemp)"
  jq --argjson entry "$entry_json" --arg ts "$(now_iso)" \
    '.entries += [$entry] | .updated_at = $ts' \
    "$path" > "$tmp" && mv "$tmp" "$path"
}

mission_dir() {
  echo "$MISSIONS_DIR/$1"
}

mission_json_path() {
  echo "$(mission_dir "$1")/mission.json"
}

mission_md_path() {
  echo "$(mission_dir "$1")/mission.md"
}

require_mission() {
  local mission_id="$1"
  local path
  path="$(mission_json_path "$mission_id")"
  if [ ! -f "$path" ]; then
    echo "ERROR: no such mission: $mission_id" >&2
    exit 1
  fi
  echo "$path"
}

# render_mission_md MISSION_ID
# Regenerates the human-readable mission.md from mission.json. Markdown is
# always a derived view; mission.json is the source of truth.
render_mission_md() {
  local mission_id="$1"
  local json_path md_path
  json_path="$(require_mission "$mission_id")"
  md_path="$(mission_md_path "$mission_id")"

  local title objective state next created updated origin
  title=$(jq -r '.title' "$json_path")
  objective=$(jq -r '.objective' "$json_path")
  state=$(jq -r '.current_state' "$json_path")
  next=$(jq -r '.next_recommended_action' "$json_path")
  created=$(jq -r '.created_at' "$json_path")
  updated=$(jq -r '.updated_at' "$json_path")
  origin=$(jq -r '.origin' "$json_path")

  {
    echo "# $title"
    echo
    echo "- **mission_id:** $mission_id"
    echo "- **origin:** $origin"
    echo "- **current_state:** $state"
    echo "- **created_at:** $created"
    echo "- **updated_at:** $updated"
    echo
    echo "## Objective"
    echo "$objective"
    echo
    echo "## Source Context"
    jq -r '.source_context | "- channel: \(.channel // "-")\n- capture_id: \(.capture_id // "-")\n- captured_at: \(.captured_at // "-")\n- raw_text: \(.raw_text // "-")"' "$json_path"
    echo
    echo "## Constraints"
    jq -r '.constraints[]? | "- \(.)"' "$json_path"
    echo
    echo "## Acceptance Criteria"
    jq -r '.acceptance_criteria[]? | "- \(.)"' "$json_path"
    echo
    echo "## Evidence"
    jq -r '.evidence[]? | "- [\(.evidence_id)] \(.description) (\(.ref // "no ref"))"' "$json_path"
    echo
    echo "## Artifacts Created"
    jq -r '.artifacts_created[]? | "- [\(.asset_id)] (\(.type)) \(.description) \(.path // "")"' "$json_path"
    echo
    echo "## Decisions Made"
    jq -r '.decisions_made[]? | "- [\(.decision_id)] intent: \(.intent) | reasoning: \(.reasoning) | outcome: \(.outcome) | lesson: \(.lesson_learned // "-")"' "$json_path"
    echo
    echo "## Validation Results"
    jq -r '.validation_results[]? | "- [\(.validation_id)] \(.method) -> \(.result)"' "$json_path"
    echo
    echo "## Commercial Opportunities"
    jq -r '.commercial_opportunities[]? | "- [\(.commercial_id)] \(.packaging_form) for \(.who_benefits): \(.problem_solved) (sellable: \(.sellable))"' "$json_path"
    echo
    echo "## Lessons Learned"
    jq -r '.lessons_learned[]? | "- \(.)"' "$json_path"
    echo
    echo "## Next Recommended Action"
    echo "$next"
    echo
    echo "## Links"
    jq -r '.links | "- predecessors: \(.predecessor_missions | join(", "))\n- successors: \(.successor_missions | join(", "))"' "$json_path"
  } > "$md_path"
}
