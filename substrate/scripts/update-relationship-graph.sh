#!/usr/bin/env bash
# Module 06 (Continuity Graph) + Module 07 (Mobile Knowledge Graph).
#
# relationship_graph.json is kept as a pure, deterministic function of the
# rest of the substrate wherever possible (missions, registries, capability
# genome, evidence packages) - `rebuild` recomputes nodes/edges from scratch
# every time, so the graph can never drift out of sync or accumulate stale
# edges. Entities that aren't derivable from files (people, topics, concepts,
# projects, research, reasoning sessions) are recorded separately as
# manual_nodes/manual_edges and merged in on every rebuild.
#
# Usage:
#   update-relationship-graph.sh rebuild
#   update-relationship-graph.sh add-node TYPE ID [--label TEXT]
#   update-relationship-graph.sh add-edge FROM_ID TO_ID RELATION

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

cmd="${1:?subcommand required (rebuild|add-node|add-edge)}"; shift

case "$cmd" in
  add-node)
    type="${1:?type required}"; id="${2:?id required}"; shift 2
    label=""
    while [ $# -gt 0 ]; do case "$1" in --label) label="$2"; shift 2 ;; *) shift ;; esac; done
    tmp="$(mktemp)"
    jq --arg type "$type" --arg id "$id" --arg label "$label" \
      '.manual_nodes |= (map(select(.id != $id)) + [{id: $id, type: $type, label: $label}])' \
      "$RELATIONSHIP_GRAPH" > "$tmp" && mv "$tmp" "$RELATIONSHIP_GRAPH"
    echo "Added manual node: $id ($type)"
    ;;

  add-edge)
    from="${1:?from required}"; to="${2:?to required}"; relation="${3:?relation required}"
    tmp="$(mktemp)"
    jq --arg from "$from" --arg to "$to" --arg rel "$relation" \
      '.manual_edges |= (. + [{from: $from, to: $to, relation: $rel}] | unique)' \
      "$RELATIONSHIP_GRAPH" > "$tmp" && mv "$tmp" "$RELATIONSHIP_GRAPH"
    echo "Added manual edge: $from -[$relation]-> $to"
    ;;

  rebuild)
    nodes_json='[]'
    edges_json='[]'

    add_nodes() { nodes_json="$(jq -c --argjson add "$1" '. + $add' <<<"$nodes_json")"; }
    add_edges() { edges_json="$(jq -c --argjson add "$1" '. + $add' <<<"$edges_json")"; }

    # Desktop missions (MSN)
    if [ -f "$(registry_path mission)" ]; then
      add_nodes "$(jq -c '[.entries[]? | {id: .mission_id, type: "mission", label: .title}]' "$(registry_path mission)")"
    fi

    # Phone sensor missions (PSM)
    if [ -d "$PHONE_MISSIONS_DIR" ]; then
      for f in "$PHONE_MISSIONS_DIR"/*.json; do
        [ -e "$f" ] || continue
        add_nodes "$(jq -c '[{id: .mission_id, type: "phone_sensor_mission", label: .objective}]' "$f")"
        add_edges "$(jq -c '[.related_missions[]? | {from: (input_filename | split("/") | last | rtrimstr(".json")), to: ., relation: "promoted_to"}]' "$f")"
      done
    fi

    # Generic registries: entry links back to its mission
    for reg in knowledge decision evidence prompt workflow commercial asset; do
      path="$(registry_path "$reg")"
      [ -f "$path" ] || continue
      id_field="${reg}_id"
      add_nodes "$(jq -c --arg t "$reg" --arg idf "$id_field" \
        '[.entries[]? | {id: (.[$idf] // .evidence_id // .decision_id // .knowledge_id // .prompt_id // .workflow_id // .commercial_id // .asset_id), type: $t, label: (.description // .title // .intent // "")}]' \
        "$path")"
      add_edges "$(jq -c --arg t "$reg" --arg idf "$id_field" \
        '[.entries[]? | select(.mission_id != null) | {from: (.[$idf] // .evidence_id // .decision_id // .knowledge_id // .prompt_id // .workflow_id // .commercial_id // .asset_id), to: .mission_id, relation: ($t + "_of_mission")}]' \
        "$path")"
    done

    # Capability genome: capability <-> contributing missions
    if [ -f "$CAPABILITY_GENOME" ]; then
      add_nodes "$(jq -c '[.capabilities[]? | {id: .capability_id, type: "capability", label: .description}]' "$CAPABILITY_GENOME")"
      add_edges "$(jq -c '[.capabilities[]? as $c | $c.contributing_missions[]? | {from: $c.capability_id, to: ., relation: "strengthened_by_mission"}]' "$CAPABILITY_GENOME")"
      add_edges "$(jq -c '[.capabilities[]? as $c | $c.strengthens[]? | {from: $c.capability_id, to: ., relation: "strengthens"}]' "$CAPABILITY_GENOME")"
      add_edges "$(jq -c '[.capabilities[]? as $c | $c.produces[]? | {from: $c.capability_id, to: ., relation: "produces"}]' "$CAPABILITY_GENOME")"
    fi

    # Evidence packages: package -> mission
    if [ -d "$EVIDENCE_PACKAGES_DIR" ]; then
      for f in "$EVIDENCE_PACKAGES_DIR"/*.json; do
        [ -e "$f" ] || continue
        add_nodes "$(jq -c '[{id: .package_id, type: "evidence_package", label: .objective}]' "$f")"
        add_edges "$(jq -c '[{from: .package_id, to: .mission_id, relation: "evidence_package_of_mission"}]' "$f")"
      done
    fi

    # Dedup nodes by id (first write wins), dedup edges exactly.
    nodes_json="$(jq -c 'group_by(.id) | map(.[0])' <<<"$nodes_json")"
    edges_json="$(jq -c 'unique' <<<"$edges_json")"

    ts="$(now_iso)"
    tmp="$(mktemp)"
    jq \
      --argjson nodes "$nodes_json" --argjson edges "$edges_json" --arg ts "$ts" \
      '
      (.manual_nodes // []) as $mn | (.manual_edges // []) as $me |
      .generated_at = $ts |
      .nodes = (($nodes + $mn) | group_by(.id) | map(.[0])) |
      .edges = (($edges + $me) | unique)
      ' "$RELATIONSHIP_GRAPH" > "$tmp" && mv "$tmp" "$RELATIONSHIP_GRAPH"

    node_count=$(jq '.nodes | length' "$RELATIONSHIP_GRAPH")
    edge_count=$(jq '.edges | length' "$RELATIONSHIP_GRAPH")
    echo "Rebuilt relationship graph: $node_count nodes, $edge_count edges."
    ;;

  *)
    echo "Unknown subcommand: $cmd" >&2
    exit 1
    ;;
esac
