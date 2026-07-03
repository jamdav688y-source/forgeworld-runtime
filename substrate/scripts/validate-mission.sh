#!/usr/bin/env bash
# Checks a mission against the Primary Law: every completed operation must
# leave at least one reusable asset, and every decision must be reviewable
# (intent, evidence, reasoning, outcome present).
#
# Usage: validate-mission.sh MISSION_ID
# Exit 0 = passes, exit 1 = incomplete (prints what is missing).

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

mission_id="${1:?mission_id required}"
json_path="$(require_mission "$mission_id")"

fail=0
check() {
  local desc="$1" ok="$2"
  if [ "$ok" = "0" ]; then
    echo "MISSING: $desc"
    fail=1
  fi
}

artifacts=$(jq '.artifacts_created | length' "$json_path")
check "no reusable asset recorded (artifacts_created empty)" "$([ "$artifacts" -gt 0 ] && echo 1 || echo 0)"

next_action=$(jq -r '.next_recommended_action' "$json_path")
check "next_recommended_action not set" "$([ -n "$next_action" ] && echo 1 || echo 0)"

decisions_incomplete=$(jq '[.decisions_made[] | select((.intent|length)==0 or (.evidence|length)==0 or (.reasoning|length)==0 or (.outcome|length)==0)] | length' "$json_path")
check "decision(s) missing intent/evidence/reasoning/outcome" "$([ "$decisions_incomplete" -eq 0 ] && echo 1 || echo 0)"

commercial=$(jq '.commercial_opportunities | length' "$json_path")
check "commercial question not answered (Who benefits? Can it be sold/packaged?)" "$([ "$commercial" -gt 0 ] && echo 1 || echo 0)"

evidence=$(jq '.evidence | length' "$json_path")
check "no evidence attached" "$([ "$evidence" -gt 0 ] && echo 1 || echo 0)"

if [ "$fail" -eq 0 ]; then
  ts="$(now_iso)"
  update_json_tmp="$(mktemp)"
  jq --arg ts "$ts" '.validation_results += [{validation_id: ("VAL-" + $ts), method: "primary-law-check", result: "pass", validated_at: $ts}] | .updated_at = $ts' \
    "$json_path" > "$update_json_tmp" && mv "$update_json_tmp" "$json_path"
  render_mission_md "$mission_id"
  echo "PASS: $mission_id satisfies the Primary Law (teaches the substrate)."
else
  echo "FAIL: $mission_id is incomplete. See MISSING lines above."
  exit 1
fi
