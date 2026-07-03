#!/usr/bin/env bash
# PHONE: Module 01 (Local Mission Capture Engine) + Module 02 (Offline Event
# Journal) in one offline-safe step. Extends capture-idea.sh's queue (which
# still works unchanged) with a fully schema-validated sensor mission object
# for when the operator has more structured signal to record.
#
# No network required. No cloud dependency. Deterministic IDs derived from
# content + time.
#
# Usage:
#   sensor-capture.sh --objective "..." --observation "..." [--context "..."]
#     [--evidence "..."] [--evidence-type voice_note] [--location "..."]
#     [--confidence 0.8] [--priority normal] [--governance-class informational]
#     [--commercial-potential medium] [--capability-contribution "..."]
#     [--operator-notes "..."] [--related-mission MSN-... ...] [--force]
#
# Prints the new (or matched-duplicate) mission_id.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

objective="" observation="" context="" evidence="" evidence_type="manual_note"
location="null" confidence="unknown" priority="normal" governance_class="unclassified"
commercial_potential="unknown" capability_contribution="unknown" operator_notes=""
suggested_next_action=""
force=0
related_missions=()

while [ $# -gt 0 ]; do
  case "$1" in
    --objective) objective="$2"; shift 2 ;;
    --observation) observation="$2"; shift 2 ;;
    --context) context="$2"; shift 2 ;;
    --evidence) evidence="$2"; shift 2 ;;
    --evidence-type) evidence_type="$2"; shift 2 ;;
    --location) location="$2"; shift 2 ;;
    --confidence) confidence="$2"; shift 2 ;;
    --priority) priority="$2"; shift 2 ;;
    --governance-class) governance_class="$2"; shift 2 ;;
    --commercial-potential) commercial_potential="$2"; shift 2 ;;
    --capability-contribution) capability_contribution="$2"; shift 2 ;;
    --operator-notes) operator_notes="$2"; shift 2 ;;
    --next-action) suggested_next_action="$2"; shift 2 ;;
    --related-mission) related_missions+=("$2"); shift 2 ;;
    --force) force=1; shift 1 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$objective" ] || [ -z "$observation" ]; then
  echo "Usage: sensor-capture.sh --objective TEXT --observation TEXT [...]" >&2
  exit 1
fi

# Primary Law: no capture without a next action. Default to the standard
# handoff if the operator didn't specify one.
if [ -z "$suggested_next_action" ]; then
  suggested_next_action="Review on laptop and run promote-sensor-mission.sh to fold this into the desktop mission pipeline."
fi

mkdir -p "$PHONE_MISSIONS_DIR"

content_hash="$(sha256_str "${objective}|${observation}|${context}")"

# Duplicate detection: same objective+observation+context already captured.
if [ "$force" != "1" ] && [ -d "$PHONE_MISSIONS_DIR" ]; then
  existing_id="$(grep -l "\"content_hash\": \"$content_hash\"" "$PHONE_MISSIONS_DIR"/*.json 2>/dev/null | head -1 || true)"
  if [ -n "$existing_id" ]; then
    dup_id="$(jq -r '.mission_id' "$existing_id")"
    echo "DUPLICATE of $dup_id (same objective+observation+context). Use --force to record anyway." >&2
    echo "$dup_id"
    exit 0
  fi
fi

mission_id="$(gen_id PSM)"
ts="$(now_iso)"
related_json="[]"
if [ "${#related_missions[@]}" -gt 0 ]; then
  related_json="$(printf '%s\n' "${related_missions[@]}" | jq -R . | jq -sc .)"
fi
[ "$location" != "null" ] && location_json="\"$location\"" || location_json="null"

mission_json="$(jq -nc \
  --arg mission_id "$mission_id" --arg ts "$ts" --arg objective "$objective" \
  --arg observation "$observation" --arg context "$context" --arg evidence "$evidence" \
  --arg evidence_type "$evidence_type" --argjson location "$location_json" \
  --arg confidence "$confidence" --arg priority "$priority" --arg governance_class "$governance_class" \
  --arg commercial_potential "$commercial_potential" --argjson related_missions "$related_json" \
  --arg capability_contribution "$capability_contribution" --arg operator_notes "$operator_notes" \
  --arg content_hash "$content_hash" --arg suggested_next_action "$suggested_next_action" \
  '{
    mission_id: $mission_id, timestamp: $ts, objective: $objective, observation: $observation,
    context: $context, evidence: $evidence, evidence_type: $evidence_type, location: $location,
    confidence: ($confidence | (try tonumber catch $confidence)),
    priority: $priority, governance_class: $governance_class,
    commercial_potential: $commercial_potential, related_missions: $related_missions,
    related_knowledge_nodes: [], supporting_assets: [], required_specialists: [],
    validation_status: "unvalidated", suggested_next_action: $suggested_next_action,
    synchronization_state: "local_only", operator_notes: $operator_notes,
    capability_contribution: $capability_contribution, content_hash: $content_hash,
    journal_event_id: null
  }')"

event_id="$(journal_append "$evidence_type" phone "$mission_json" "$mission_id")"
mission_json="$(echo "$mission_json" | jq --arg eid "$event_id" '.journal_event_id = $eid')"
echo "$mission_json" > "$PHONE_MISSIONS_DIR/$mission_id.json"

echo "Captured sensor mission: $mission_id (journal event $event_id)"
echo "$mission_id"
