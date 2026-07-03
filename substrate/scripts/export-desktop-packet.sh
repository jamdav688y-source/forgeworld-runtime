#!/usr/bin/env bash
# Module 05: Phone -> Desktop Synchronization.
#
# Produces a deterministic, human-readable, offline-transferable manifest at
# sync/desktop_export_manifest.json listing every substrate file that makes
# up "the packet" (missions, evidence packages, registries/knowledge nodes,
# capability genome, relationship graph, validation state) together with a
# sha256 of each file's current content and a whole-packet integrity hash.
#
# This reuses the existing sync/ convention already implied by
# scripts/forge-sync-pack.sh (which tars phone-side files into sync/) rather
# than inventing a second sync location. Run scripts/forge-sync-pack.sh
# separately if you also want a transferable tarball; this script only
# produces the manifest that describes what's in the substrate at export
# time, independent of how it's physically moved.
#
# Usage: export-desktop-packet.sh
# Deterministic and read-only: this script never writes anywhere except the
# manifest file itself, and never touches the event journal it reports on
# (an export that logged itself before hashing the journal would be hashing
# a journal it had just changed - not deterministic). Running it twice with
# no substrate changes in between produces identical file lists and hashes
# (only generated_at differs). Run update-relationship-graph.sh rebuild
# yourself first if you want the graph reflected in this export to be fresh.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

mkdir -p "$SYNC_DIR"

files_json='[]'
add_file() {
  local path="$1" category="$2"
  [ -f "$path" ] || return 0
  local rel hash size
  rel="${path#"$REPO_ROOT"/}"
  hash="$(sha256_file "$path")"
  size="$(wc -c < "$path" | tr -d ' ')"
  files_json="$(jq -c --arg path "$rel" --arg cat "$category" --arg hash "$hash" --arg size "$size" \
    '. + [{path: $path, category: $cat, sha256: $hash, bytes: ($size | tonumber)}]' <<<"$files_json")"
}

# Mission objects (desktop + phone)
for f in "$MISSIONS_DIR"/*/mission.json; do add_file "$f" mission; done
for f in "$PHONE_MISSIONS_DIR"/*.json; do add_file "$f" phone_sensor_mission; done

# Evidence packages
for f in "$EVIDENCE_PACKAGES_DIR"/*.json; do add_file "$f" evidence_package; done

# Registries / knowledge nodes
for reg in mission knowledge decision evidence prompt workflow commercial asset; do
  add_file "$(registry_path "$reg")" registry
done

# Capability updates + relationship graph + event journal (validation state / lineage)
add_file "$CAPABILITY_GENOME" capability_genome
add_file "$RELATIONSHIP_GRAPH" relationship_graph
add_file "$EVENT_JOURNAL" event_journal

# Deterministic ordering
files_json="$(jq -c 'sort_by(.path)' <<<"$files_json")"

mission_count=$(jq '[.[] | select(.category=="mission")] | length' <<<"$files_json")
psm_count=$(jq '[.[] | select(.category=="phone_sensor_mission")] | length' <<<"$files_json")
package_count=$(jq '[.[] | select(.category=="evidence_package")] | length' <<<"$files_json")

ts="$(now_iso)"
packet_json="$(jq -nc \
  --argjson files "$files_json" \
  --arg mission_count "$mission_count" --arg psm_count "$psm_count" --arg package_count "$package_count" \
  --arg ts "$ts" \
  '{
    packet_version: "1.0.0",
    generated_at: $ts,
    origin: "laptop",
    counts: {
      missions: ($mission_count | tonumber),
      phone_sensor_missions: ($psm_count | tonumber),
      evidence_packages: ($package_count | tonumber)
    },
    files: $files,
    operator_notes: "",
    validation_state: "unvalidated"
  }')"

packet_hash="$(sha256_str "$(jq -Sc '.files' <<<"$packet_json")")"
manifest_json="$(jq --arg hash "$packet_hash" '. + {packet_integrity_hash: $hash}' <<<"$packet_json")"

echo "$manifest_json" | jq . > "$EXPORT_MANIFEST"

echo "Wrote $EXPORT_MANIFEST"
echo "Packet integrity hash: $packet_hash"
echo "Files: $(jq 'length' <<<"$files_json")  Missions: $mission_count  Sensor missions: $psm_count  Evidence packages: $package_count"
