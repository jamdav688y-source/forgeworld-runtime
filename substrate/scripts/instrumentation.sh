#!/usr/bin/env bash
# Module 09: Instrumentation.
#
# Computes real metrics from the files on disk (no hidden runtime state) and
# appends one snapshot line to instrumentation_history.jsonl, so growth over
# time can be measured later instead of only seeing a single point-in-time
# count. substrate-status.sh (Module 10) calls this for its numbers; you can
# also run it directly.
#
# Usage: instrumentation.sh [--quiet]

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

quiet=0
[ "${1:-}" = "--quiet" ] && quiet=1

count_files() { local d="$1" p="$2"; [ -d "$d" ] || { echo 0; return; }; find "$d" -maxdepth 1 -name "$p" | wc -l | tr -d ' '; }

mission_count=$(jq '.entries | length' "$(registry_path mission)")
psm_count=$(count_files "$PHONE_MISSIONS_DIR" "*.json")
knowledge_count=$(jq '.entries | length' "$(registry_path knowledge)")
evidence_count=$(jq '.entries | length' "$(registry_path evidence)")
evidence_package_count=$(count_files "$EVIDENCE_PACKAGES_DIR" "*.json")
capability_count=$(jq '.capabilities | length' "$CAPABILITY_GENOME" 2>/dev/null || echo 0)
capability_reuse_total=$(jq '[.capabilities[]?.reuse_frequency] | add // 0' "$CAPABILITY_GENOME" 2>/dev/null || echo 0)
commercial_count=$(jq '.entries | length' "$(registry_path commercial)")
pending_queue=$( [ -f "$QUEUE_FILE" ] && jq -R -s '[split("\n")[] | select(length>0) | fromjson | select(.status=="queued")] | length' "$QUEUE_FILE" || echo 0)
pending_psm=$(find "$PHONE_MISSIONS_DIR" -maxdepth 1 -name "*.json" 2>/dev/null -exec jq -r '.synchronization_state' {} \; 2>/dev/null | grep -c '^local_only$' || true)
validation_queue=0
for mf in "$MISSIONS_DIR"/*/mission.json; do
  [ -e "$mf" ] || continue
  passed=$(jq '[.validation_results[]? | select(.method=="primary-law-check" and .result=="pass")] | length' "$mf")
  [ "$passed" -eq 0 ] && validation_queue=$((validation_queue + 1))
done
node_count=$(jq '.nodes | length' "$RELATIONSHIP_GRAPH" 2>/dev/null || echo 0)
edge_count=$(jq '.edges | length' "$RELATIONSHIP_GRAPH" 2>/dev/null || echo 0)
density="0"
[ "$node_count" -gt 0 ] && density=$(echo "scale=3; $edge_count / $node_count" | bc 2>/dev/null || jq -n --argjson e "$edge_count" --argjson n "$node_count" '($e / $n)')
journal_event_count=$( [ -f "$EVENT_JOURNAL" ] && wc -l < "$EVENT_JOURNAL" | tr -d ' ' || echo 0)
last_export_age="never"
if [ -f "$EXPORT_MANIFEST" ]; then
  last_export_ts=$(jq -r '.generated_at' "$EXPORT_MANIFEST")
  last_export_age="$last_export_ts"
fi

ts="$(now_iso)"
snapshot="$(jq -nc \
  --arg ts "$ts" \
  --argjson mission_count "$mission_count" --argjson psm_count "$psm_count" \
  --argjson knowledge_count "$knowledge_count" --argjson evidence_count "$evidence_count" \
  --argjson evidence_package_count "$evidence_package_count" \
  --argjson capability_count "$capability_count" --argjson capability_reuse_total "$capability_reuse_total" \
  --argjson commercial_count "$commercial_count" --argjson pending_queue "$pending_queue" \
  --argjson pending_psm "$pending_psm" --argjson validation_queue "$validation_queue" \
  --argjson node_count "$node_count" --argjson edge_count "$edge_count" \
  --argjson density "$density" --argjson journal_event_count "$journal_event_count" \
  --arg last_export_at "$last_export_age" \
  '{
    timestamp: $ts,
    mission_count: $mission_count, phone_sensor_mission_count: $psm_count,
    knowledge_growth: $knowledge_count, evidence_growth: $evidence_count,
    evidence_package_count: $evidence_package_count,
    capability_growth: $capability_count, capability_reuse_total: $capability_reuse_total,
    commercial_signals: $commercial_count,
    synchronization_health: { pending_queue_captures: $pending_queue, pending_phone_sensor_missions: $pending_psm, last_export_at: $last_export_at },
    validation_queue: $validation_queue,
    relationship_density: $density,
    relationship_nodes: $node_count, relationship_edges: $edge_count,
    operator_activity_events: $journal_event_count
  }')"

mkdir -p "$SUBSTRATE_DIR"
echo "$snapshot" >> "$INSTRUMENTATION_HISTORY"

if [ "$quiet" != "1" ]; then
  echo "$snapshot" | jq .
fi
