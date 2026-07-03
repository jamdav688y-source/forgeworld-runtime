#!/usr/bin/env bash
# LAPTOP: create a new mission from the shared template and register it.
#
# Usage:
#   new-mission.sh --title "..." --objective "..." [--origin phone|laptop]
#                   [--channel CHANNEL --capture-id CAP-... --raw-text "..." --captured-at TS]
#
# Prints the new mission_id on success.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

title="" objective="" origin="laptop"
channel="" capture_id="" raw_text="" captured_at=""

while [ $# -gt 0 ]; do
  case "$1" in
    --title) title="$2"; shift 2 ;;
    --objective) objective="$2"; shift 2 ;;
    --origin) origin="$2"; shift 2 ;;
    --channel) channel="$2"; shift 2 ;;
    --capture-id) capture_id="$2"; shift 2 ;;
    --raw-text) raw_text="$2"; shift 2 ;;
    --captured-at) captured_at="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$title" ] || [ -z "$objective" ]; then
  echo "Usage: new-mission.sh --title TITLE --objective OBJECTIVE [...]" >&2
  exit 1
fi

mission_id="$(gen_id MSN)"
ts="$(now_iso)"
dir="$(mission_dir "$mission_id")"
mkdir -p "$dir"

jq -n \
  --arg mission_id "$mission_id" \
  --arg title "$title" \
  --arg objective "$objective" \
  --arg origin "$origin" \
  --arg channel "$channel" \
  --arg capture_id "$capture_id" \
  --arg raw_text "$raw_text" \
  --arg captured_at "$captured_at" \
  --arg ts "$ts" \
  '{
    mission_id: $mission_id,
    title: $title,
    objective: $objective,
    origin: $origin,
    source_context: {
      channel: $channel,
      capture_id: $capture_id,
      raw_text: $raw_text,
      captured_at: $captured_at
    },
    evidence: [],
    constraints: [],
    acceptance_criteria: [],
    current_state: "captured",
    artifacts_created: [],
    decisions_made: [],
    validation_results: [],
    commercial_opportunities: [],
    lessons_learned: [],
    next_recommended_action: "",
    links: { predecessor_missions: [], successor_missions: [] },
    created_at: $ts,
    updated_at: $ts
  }' > "$(mission_json_path "$mission_id")"

render_mission_md "$mission_id"

append_registry_entry mission "$(jq -n \
  --arg mission_id "$mission_id" --arg title "$title" --arg origin "$origin" \
  --arg state "captured" --arg ts "$ts" \
  '{mission_id: $mission_id, title: $title, origin: $origin, current_state: $state, created_at: $ts, updated_at: $ts}')"

echo "$mission_id"
