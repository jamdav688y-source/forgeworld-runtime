#!/usr/bin/env bash
# LAPTOP: promote a phone sensor mission (PSM-...) into a full desktop
# mission (MSN-...) using the existing new-mission.sh, exactly the same way
# process-queue.sh already promotes capture/queue.jsonl entries. This is the
# join point between the Ascension modules and last session's substrate -
# one continuity system, not two.
#
# Usage: promote-sensor-mission.sh PSM_ID
# Prints the resulting MSN mission_id.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

psm_id="${1:?PSM mission_id required}"
psm_path="$PHONE_MISSIONS_DIR/$psm_id.json"
if [ ! -f "$psm_path" ]; then
  echo "ERROR: no such sensor mission: $psm_id" >&2
  exit 1
fi

sync_state="$(jq -r '.synchronization_state' "$psm_path")"
if [ "$sync_state" = "promoted" ]; then
  echo "Already promoted: $(jq -r '.related_missions[0] // "unknown"' "$psm_path")" >&2
  exit 0
fi

objective="$(jq -r '.objective' "$psm_path")"
observation="$(jq -r '.observation' "$psm_path")"
context="$(jq -r '.context' "$psm_path")"
evidence_type="$(jq -r '.evidence_type' "$psm_path")"
ts="$(jq -r '.timestamp' "$psm_path")"

mission_id="$("$here/new-mission.sh" \
  --title "[$evidence_type] ${observation:0:60}" \
  --objective "$objective" \
  --origin phone \
  --channel "$evidence_type" \
  --capture-id "$psm_id" \
  --raw-text "$observation | context: $context" \
  --captured-at "$ts")"

evidence_id="$(gen_id EVD)"
entry_json="$(jq -n --arg id "$evidence_id" --arg desc "Promoted from sensor mission $psm_id: $(jq -r '.evidence' "$psm_path")" --arg ref "$psm_id" --arg ts "$ts" \
  '{evidence_id: $id, description: $desc, ref: $ref, captured_at: $ts}')"
tmp="$(mktemp)"
jq --argjson e "$entry_json" --arg ts "$(now_iso)" '.evidence += [$e] | .updated_at = $ts' \
  "$(mission_json_path "$mission_id")" > "$tmp" && mv "$tmp" "$(mission_json_path "$mission_id")"
render_mission_md "$mission_id"

append_registry_entry evidence "$(jq -n --arg id "$evidence_id" --arg mission_id "$mission_id" --arg type "$evidence_type" \
  --arg desc "$(jq -r '.evidence' "$psm_path")" --arg ts "$ts" \
  '{evidence_id: $id, mission_id: $mission_id, type: $type, description: $desc, captured_by: "phone", captured_at: $ts}')"

tmp="$(mktemp)"
jq --arg mid "$mission_id" '.synchronization_state = "promoted" | .related_missions += [$mid]' \
  "$psm_path" > "$tmp" && mv "$tmp" "$psm_path"

journal_append mission_update laptop "$(jq -nc --arg psm "$psm_id" --arg mid "$mission_id" \
  '{promoted_from: $psm, promoted_to: $mid}')" "$psm_id" "$mission_id" >/dev/null

echo "Promoted $psm_id -> $mission_id"
echo "$mission_id"
