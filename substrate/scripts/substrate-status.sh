#!/usr/bin/env bash
# The dashboard. Per the Visual Principle: shows only real substrate state,
# no decorative output. Every line here corresponds to an actual file on
# disk at the moment you run it.

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
echo "==============================================="
