#!/usr/bin/env bash
# The dashboard (Module 10: Operator Console). Per the Visual Principle:
# shows only real substrate state, no decorative output. Every line here
# corresponds to an actual file on disk at the moment you run it.
#
# Extended in place for CONTINUITY_SUBSTRATE_ASCENSION_V1 rather than built
# as a second, competing console - the sections above this comment are
# unchanged from the original substrate; everything below "Phone sensor
# missions" is new.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

echo "=== FORGEWORLD CONTINUITY SUBSTRATE STATUS ==="
echo "Generated: $(now_iso)"
echo

echo "-- Missions by state --"
if [ -d "$MISSIONS_DIR" ]; then
  jq -r '.entries[].current_state' "$(registry_path mission)" 2>/dev/null | sort | uniq -c | sort -rn || echo "none"
fi
total_missions=$(jq '.entries | length' "$(registry_path mission)")
echo "Total missions: $total_missions"
echo

echo "-- Pending phone/field captures (not yet promoted) --"
if [ -f "$QUEUE_FILE" ]; then
  pending=$(jq -R -s '[split("\n")[] | select(length>0) | fromjson | select(.status=="queued")] | length' "$QUEUE_FILE")
  echo "Queued: $pending"
else
  echo "Queued: 0 (no queue file yet)"
fi
echo

echo "-- Registry sizes --"
for reg in mission knowledge decision evidence prompt workflow commercial asset; do
  n=$(jq '.entries | length' "$(registry_path "$reg")")
  printf "%-12s %s\n" "$reg" "$n"
done
echo

echo "-- Missions missing a next_recommended_action --"
found=0
for mf in "$MISSIONS_DIR"/*/mission.json; do
  [ -e "$mf" ] || continue
  na=$(jq -r '.next_recommended_action' "$mf")
  if [ -z "$na" ]; then
    jq -r '.mission_id' "$mf"
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "none"
echo

echo "-- Missions not yet validated (no primary-law-check pass) --"
found=0
for mf in "$MISSIONS_DIR"/*/mission.json; do
  [ -e "$mf" ] || continue
  passed=$(jq '[.validation_results[]? | select(.method=="primary-law-check" and .result=="pass")] | length' "$mf")
  if [ "$passed" -eq 0 ]; then
    jq -r '.mission_id' "$mf"
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "none"
echo

metrics="$("$here/instrumentation.sh" --quiet && tail -1 "$INSTRUMENTATION_HISTORY")"

echo "-- Phone sensor missions (PSM) --"
if [ -d "$PHONE_MISSIONS_DIR" ]; then
  total_psm=$(find "$PHONE_MISSIONS_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  echo "Total: $total_psm"
  for f in "$PHONE_MISSIONS_DIR"/*.json; do
    [ -e "$f" ] || continue
    jq -r '"  \(.mission_id)  sync=\(.synchronization_state)  validation=\(.validation_status)"' "$f"
  done
else
  echo "Total: 0"
fi
echo

echo "-- Evidence package queue (built, awaiting sync/review) --"
found=0
if [ -d "$EVIDENCE_PACKAGES_DIR" ]; then
  for f in "$EVIDENCE_PACKAGES_DIR"/*.json; do
    [ -e "$f" ] || continue
    state=$(jq -r '.synchronization_metadata.state' "$f")
    if [ "$state" != "synced" ]; then
      jq -r '"  \(.package_id)  mission=\(.mission_id)  state=\(.synchronization_metadata.state)"' "$f"
      found=1
    fi
  done
fi
[ "$found" -eq 0 ] && echo "  none"
echo

echo "-- Synchronization status --"
echo "  pending queue captures:        $(echo "$metrics" | jq -r '.synchronization_health.pending_queue_captures')"
echo "  pending phone sensor missions: $(echo "$metrics" | jq -r '.synchronization_health.pending_phone_sensor_missions')"
echo "  last desktop export at:        $(echo "$metrics" | jq -r '.synchronization_health.last_export_at')"
echo

echo "-- Knowledge / capability growth --"
echo "  knowledge_registry entries: $(echo "$metrics" | jq -r '.knowledge_growth')"
echo "  capabilities tracked:       $(echo "$metrics" | jq -r '.capability_growth')"
echo "  capability reuse (total):   $(echo "$metrics" | jq -r '.capability_reuse_total')"
echo "  relationship graph:         $(echo "$metrics" | jq -r '.relationship_nodes') nodes / $(echo "$metrics" | jq -r '.relationship_edges') edges (density $(echo "$metrics" | jq -r '.relationship_density'))"
echo

echo "-- Governance alerts (unknown/unclassified governance fields) --"
found=0
for f in "$PHONE_MISSIONS_DIR"/*.json; do
  [ -e "$f" ] || continue
  gc=$(jq -r '.governance_class' "$f")
  conf=$(jq -r '.confidence' "$f")
  if [ "$gc" = "unknown" ] || [ "$conf" = "unknown" ]; then
    jq -r '"  \(.mission_id)  governance_class=\(.governance_class)  confidence=\(.confidence)"' "$f"
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "  none"
echo

echo "-- Commercial opportunities (sellable) --"
found=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  echo "  $line"
  found=1
done < <(jq -r '.entries[]? | select(.sellable == true) | "\(.commercial_id)  \(.packaging_form)  mission=\(.mission_id)"' "$(registry_path commercial)")
[ "$found" -eq 0 ] && echo "  none"
echo

echo "-- Runtime health --"
health_ok=1
for req_file in "$CAPABILITY_GENOME" "$RELATIONSHIP_GRAPH" "$(registry_path mission)"; do
  if ! jq empty "$req_file" >/dev/null 2>&1; then
    echo "  CORRUPT OR MISSING: $req_file"
    health_ok=0
  fi
done
if [ -f "$EVENT_JOURNAL" ]; then
  bad_lines=$(jq -c . "$EVENT_JOURNAL" 2>&1 >/dev/null | wc -l | tr -d ' ')
  if [ "$bad_lines" != "0" ]; then
    echo "  event_journal.jsonl has $bad_lines unparseable line(s)"
    health_ok=0
  fi
fi
[ "$health_ok" -eq 1 ] && echo "  ok: all core substrate files parse as valid JSON"
echo "==============================================="
