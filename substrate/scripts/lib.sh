#!/usr/bin/env bash
# Shared helpers for the ForgeWorld continuity substrate.
# Sourced by every substrate script. Portable bash + jq: works on laptop
# and on phone (Termux) as long as `jq` is installed (`pkg install jq`).

set -euo pipefail

SUBSTRATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY_DIR="$SUBSTRATE_DIR/registries"
MISSIONS_DIR="$SUBSTRATE_DIR/missions"
CAPTURE_DIR="$SUBSTRATE_DIR/capture"
SCHEMA_DIR="$SUBSTRATE_DIR/schema"
QUEUE_FILE="$CAPTURE_DIR/queue.jsonl"

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
