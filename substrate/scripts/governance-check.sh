#!/usr/bin/env bash
# Module 08: Runtime Governance.
#
# Checks that a substrate object (a phone sensor mission, a desktop mission,
# or a journal event) carries the required governance fields, and reports
# any that are missing as explicitly "unknown" rather than silently blank.
# This does not block anything by itself - it is a read-only report an
# operator (or Claude, per Module 11) uses before approving an action.
#
# Usage:
#   governance-check.sh mission MISSION_ID     (PSM- or MSN-)
#   governance-check.sh event EVENT_ID

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

kind="${1:?kind required (mission|event)}"; id="${2:?id required}"

report() {
  local label="$1" val="$2" needs_approval="$3"
  printf '%-24s %-20s %s\n' "$label" "$val" "$needs_approval"
}

case "$kind" in
  mission)
    if [[ "$id" == PSM-* ]]; then
      path="$PHONE_MISSIONS_DIR/$id.json"
      [ -f "$path" ] || { echo "ERROR: no such sensor mission: $id" >&2; exit 1; }
      governance_class="$(field_or_unknown "$path" '.governance_class')"
      confidence="$(field_or_unknown "$path" '.confidence')"
      validation_status="$(field_or_unknown "$path" '.validation_status')"
      traceability="$(field_or_unknown "$path" '.journal_event_id')"
    elif [[ "$id" == MSN-* ]]; then
      path="$(mission_json_path "$id")"
      [ -f "$path" ] || { echo "ERROR: no such mission: $id" >&2; exit 1; }
      governance_class="$(jq -r '"informational"' "$path")"
      confidence="$(field_or_unknown "$path" '(.validation_results | map(select(.result=="pass")) | length | tostring) + " passing validation(s)"')"
      validation_status="$(field_or_unknown "$path" '.current_state')"
      traceability="$(jq -r '(.evidence | length | tostring) + " evidence item(s)"' "$path")"
    else
      echo "ERROR: mission id must start with PSM- or MSN-" >&2
      exit 1
    fi

    risk_score="unknown"
    approval_required="yes"
    if [ "$validation_status" = "validated" ] || [ "$validation_status" = "complete" ]; then
      approval_required="no (already validated)"
    fi

    echo "=== Governance report: $id ==="
    report "governance_classification" "$governance_class" "-"
    report "confidence" "$confidence" "-"
    report "integrity/traceability" "$traceability" "-"
    report "validation_status" "$validation_status" "-"
    report "risk_score" "$risk_score" "flag: not yet scored"
    report "operator_approval_required" "$approval_required" "-"
    ;;

  event)
    [ -f "$EVENT_JOURNAL" ] || { echo "ERROR: no event journal yet" >&2; exit 1; }
    line="$(jq -c --arg id "$id" 'select(.event_id == $id)' "$EVENT_JOURNAL" | head -1)"
    [ -n "$line" ] || { echo "ERROR: no such event: $id" >&2; exit 1; }
    echo "=== Governance report: $id ==="
    report "governance_classification" "$(echo "$line" | jq -r '.governance_classification // "unknown"')" "-"
    report "confidence" "$(echo "$line" | jq -r '.confidence // "unknown"')" "-"
    report "hash (integrity)" "$(echo "$line" | jq -r '.hash')" "-"
    report "mission_association" "$(echo "$line" | jq -c '.mission_association')" "-"
    report "lineage" "$(echo "$line" | jq -c '.lineage')" "-"
    ;;

  *)
    echo "Unknown kind: $kind (expected mission|event)" >&2
    exit 1
    ;;
esac
