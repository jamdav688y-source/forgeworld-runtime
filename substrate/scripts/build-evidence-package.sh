#!/usr/bin/env bash
# Module 03: Evidence Package Engine.
#
# Assembles a portable evidence package around one mission (either a phone
# PSM-... sensor mission or a full desktop MSN-... mission) by pulling
# together its own recorded evidence, any journal events associated with it,
# and any knowledge_registry entries already linked to it. Registers a
# summary into the existing registries/evidence_registry.json so this stays
# visible from the pipeline built last session instead of forking it.
#
# Usage: build-evidence-package.sh MISSION_ID
# Prints the new package_id.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

mission_id="${1:?mission_id required}"

if [[ "$mission_id" == PSM-* ]]; then
  mission_path="$PHONE_MISSIONS_DIR/$mission_id.json"
  [ -f "$mission_path" ] || { echo "ERROR: no such sensor mission: $mission_id" >&2; exit 1; }
  objective="$(jq -r '.objective' "$mission_path")"
  observations_json="$(jq -c '[.observation]' "$mission_path")"
  supporting_json="$(jq -c '[{evidence_id: ("inline-" + .mission_id), description: .evidence, ref: .mission_id}]' "$mission_path")"
  confidence="$(jq -r '.confidence' "$mission_path")"
  commercial_relevance="$(jq -r '.commercial_potential' "$mission_path")"
elif [[ "$mission_id" == MSN-* ]]; then
  mission_path="$(mission_json_path "$mission_id")"
  [ -f "$mission_path" ] || { echo "ERROR: no such mission: $mission_id" >&2; exit 1; }
  objective="$(jq -r '.objective' "$mission_path")"
  observations_json="$(jq -c '[.source_context.raw_text // "" ] + (.decisions_made | map(.reasoning))' "$mission_path")"
  supporting_json="$(jq -c '.evidence' "$mission_path")"
  confidence="unknown"
  commercial_relevance="$(jq -c '[.commercial_opportunities[]? | .packaging_form] | join(", ")' -r "$mission_path")"
  [ -z "$commercial_relevance" ] && commercial_relevance="unknown"
else
  echo "ERROR: mission_id must start with PSM- or MSN-" >&2
  exit 1
fi

event_ids_json="$(jq -c --arg mid "$mission_id" 'select(.mission_association[]? == $mid) | .event_id' "$EVENT_JOURNAL" 2>/dev/null | jq -sc . || echo '[]')"
evidence_ids_json="$(jq -c --arg mid "$mission_id" '[.entries[]? | select(.mission_id == $mid) | .evidence_id]' "$(registry_path evidence)")"
related_knowledge_json="$(jq -c --arg mid "$mission_id" '[.entries[]? | select(.mission_id == $mid) | .knowledge_id]' "$(registry_path knowledge)")"

mkdir -p "$EVIDENCE_PACKAGES_DIR"
package_id="$(gen_id EVP)"
ts="$(now_iso)"

core_json="$(jq -nc \
  --arg package_id "$package_id" --arg mission_id "$mission_id" --arg objective "$objective" \
  --argjson observations "$observations_json" --argjson supporting_evidence "$supporting_json" \
  --arg confidence "$confidence" --argjson related_knowledge "$related_knowledge_json" \
  --arg commercial_relevance "$commercial_relevance" \
  --argjson event_ids "$event_ids_json" --argjson evidence_ids "$evidence_ids_json" \
  --arg ts "$ts" \
  '{
    package_id: $package_id, mission_id: $mission_id, objective: $objective,
    observations: $observations, supporting_evidence: $supporting_evidence,
    confidence_score: ($confidence | (try tonumber catch $confidence)),
    related_knowledge: $related_knowledge,
    required_validation: "manual review by laptop operator before commercial use",
    commercial_relevance: $commercial_relevance,
    traceability: { mission_id: $mission_id, event_ids: $event_ids, evidence_ids: $evidence_ids },
    source_history: ([$mission_id] + $event_ids),
    created_at: $ts
  }')"

integrity_hash="$(sha256_str "$(echo "$core_json" | jq -Sc .)")"

package_json="$(echo "$core_json" | jq --arg hash "$integrity_hash" \
  '. + {integrity_hash: $hash, synchronization_metadata: {state: "local_only", generated_by: "laptop"}}')"

echo "$package_json" > "$EVIDENCE_PACKAGES_DIR/$package_id.json"

append_registry_entry evidence "$(jq -n --arg id "$package_id" --arg mission_id "$mission_id" \
  --arg ts "$ts" --arg hash "$integrity_hash" \
  '{evidence_id: $id, mission_id: $mission_id, type: "evidence_package", description: ("Assembled evidence package " + $id), captured_by: "laptop", captured_at: $ts, integrity_hash: $hash}')"

journal_append evidence_package laptop "$package_json" "$mission_id" >/dev/null

echo "Built evidence package: $package_id"
echo "$package_id"
