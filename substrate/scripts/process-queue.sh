#!/usr/bin/env bash
# LAPTOP: promote queued phone/field captures into missions.
#
# Reads capture/queue.jsonl, and for every entry with status "queued":
#   - creates a mission (new-mission.sh)
#   - records the capture as evidence on that mission (linked, not lost)
#   - marks the queue entry "promoted" with the resulting mission_id
#
# Safe to run repeatedly / offline-then-later: only "queued" entries are
# touched, so partially-synced queues never get double-processed.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

if [ ! -f "$QUEUE_FILE" ] || [ ! -s "$QUEUE_FILE" ]; then
  echo "No queued captures."
  exit 0
fi

tmp_queue="$(mktemp)"
promoted=0

while IFS= read -r line; do
  [ -z "$line" ] && continue
  status="$(echo "$line" | jq -r '.status')"
  if [ "$status" != "queued" ]; then
    echo "$line" >> "$tmp_queue"
    continue
  fi

  capture_id="$(echo "$line" | jq -r '.capture_id')"
  channel="$(echo "$line" | jq -r '.channel')"
  raw_text="$(echo "$line" | jq -r '.raw_text')"
  captured_at="$(echo "$line" | jq -r '.captured_at')"

  title="[$channel] ${raw_text:0:60}"
  mission_id="$("$here/new-mission.sh" \
    --title "$title" \
    --objective "Turn field capture $capture_id into reusable substrate capability." \
    --origin phone \
    --channel "$channel" \
    --capture-id "$capture_id" \
    --raw-text "$raw_text" \
    --captured-at "$captured_at")"

  evidence_id="$(gen_id EVD)"
  entry_json="$(jq -n --arg id "$evidence_id" --arg desc "Original field capture ($channel): $raw_text" --arg ref "$capture_id" --arg ts "$captured_at" \
    '{evidence_id: $id, description: $desc, ref: $ref, captured_at: $ts}')"

  jq --argjson e "$entry_json" --arg ts "$(now_iso)" \
    '.evidence += [$e] | .updated_at = $ts' \
    "$(mission_json_path "$mission_id")" > "$(mission_json_path "$mission_id").tmp"
  mv "$(mission_json_path "$mission_id").tmp" "$(mission_json_path "$mission_id")"
  render_mission_md "$mission_id"

  append_registry_entry evidence "$(jq -n \
    --arg id "$evidence_id" --arg mission_id "$mission_id" --arg channel "$channel" \
    --arg desc "$raw_text" --arg ts "$captured_at" \
    '{evidence_id: $id, mission_id: $mission_id, type: $channel, description: $desc, captured_by: "phone", captured_at: $ts}')"

  echo "$line" | jq -c --arg mid "$mission_id" '.status = "promoted" | .mission_id = $mid' >> "$tmp_queue"
  promoted=$((promoted + 1))
  echo "Promoted $capture_id -> $mission_id"
done < "$QUEUE_FILE"

mv "$tmp_queue" "$QUEUE_FILE"
echo "Done. Promoted $promoted capture(s)."
