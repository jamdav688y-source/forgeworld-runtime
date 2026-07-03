#!/usr/bin/env bash
# Module 04: Capability Genome.
#
# Upserts one capability into capability_genome.json. "Every completed
# mission updates capability relationships" - call this after a mission
# reaches validated/complete, once per capability it strengthened.
#
# Usage:
#   update-capability-genome.sh upsert CAPABILITY_ID \
#     --description "..." --mission MISSION_ID \
#     [--dependency ID ...] [--strengthens ID ...] [--consumes ID ...] [--produces ID ...] \
#     [--commercial-value none|low|medium|high] \
#     [--knowledge-domain NAME ...] \
#     [--automation-potential 0.0-1.0] [--learning-value none|low|medium|high]
#
# Re-running with the same capability_id merges lists (deduplicated) and
# increments reuse_frequency - it never overwrites prior contributing
# missions, so history compounds instead of being replaced.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

cmd="${1:?subcommand required (upsert)}"; shift
[ "$cmd" = "upsert" ] || { echo "Only 'upsert' is supported" >&2; exit 1; }

capability_id="${1:?capability_id required}"; shift
description="" mission_id=""
dependencies=() strengthens=() consumes=() produces=() knowledge_domains=()
commercial_value="unknown" automation_potential="unknown" learning_value="unknown"

while [ $# -gt 0 ]; do
  case "$1" in
    --description) description="$2"; shift 2 ;;
    --mission) mission_id="$2"; shift 2 ;;
    --dependency) dependencies+=("$2"); shift 2 ;;
    --strengthens) strengthens+=("$2"); shift 2 ;;
    --consumes) consumes+=("$2"); shift 2 ;;
    --produces) produces+=("$2"); shift 2 ;;
    --commercial-value) commercial_value="$2"; shift 2 ;;
    --knowledge-domain) knowledge_domains+=("$2"); shift 2 ;;
    --automation-potential) automation_potential="$2"; shift 2 ;;
    --learning-value) learning_value="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

to_json_arr() { local a=("$@"); [ "${#a[@]}" -eq 0 ] && echo '[]' && return; printf '%s\n' "${a[@]}" | jq -R . | jq -sc 'map(select(length > 0))'; }

deps_json="$(to_json_arr "${dependencies[@]:-}")"
strengthens_json="$(to_json_arr "${strengthens[@]:-}")"
consumes_json="$(to_json_arr "${consumes[@]:-}")"
produces_json="$(to_json_arr "${produces[@]:-}")"
domains_json="$(to_json_arr "${knowledge_domains[@]:-}")"
ts="$(now_iso)"

tmp="$(mktemp)"
jq \
  --arg id "$capability_id" --arg desc "$description" --arg mission_id "$mission_id" \
  --argjson deps "$deps_json" --argjson strengthens "$strengthens_json" \
  --argjson consumes "$consumes_json" --argjson produces "$produces_json" \
  --arg cv "$commercial_value" --argjson domains "$domains_json" \
  --arg ap "$automation_potential" --arg lv "$learning_value" --arg ts "$ts" \
  '
  def dedup: map(select(. != "")) | unique;
  .updated_at = $ts |
  (.capabilities | map(.capability_id) | index($id)) as $idx |
  if $idx == null then
    .capabilities += [{
      capability_id: $id, description: $desc, dependencies: $deps,
      strengthens: $strengthens, consumes: $consumes, produces: $produces,
      commercial_value: $cv, reuse_frequency: 1, knowledge_domains: $domains,
      automation_potential: ($ap | (try tonumber catch $ap)),
      learning_value: $lv,
      contributing_missions: (if $mission_id == "" then [] else [$mission_id] end),
      created_at: $ts, updated_at: $ts
    }]
  else
    .capabilities[$idx] |= (
      .description = (if $desc == "" then .description else $desc end) |
      .dependencies = ((.dependencies + $deps) | dedup) |
      .strengthens = ((.strengthens + $strengthens) | dedup) |
      .consumes = ((.consumes + $consumes) | dedup) |
      .produces = ((.produces + $produces) | dedup) |
      .knowledge_domains = ((.knowledge_domains + $domains) | dedup) |
      .commercial_value = (if $cv == "unknown" then .commercial_value else $cv end) |
      .automation_potential = (if $ap == "unknown" then .automation_potential else ($ap | (try tonumber catch $ap)) end) |
      .learning_value = (if $lv == "unknown" then .learning_value else $lv end) |
      .reuse_frequency += 1 |
      .contributing_missions = (if $mission_id == "" then .contributing_missions else (.contributing_missions + [$mission_id] | dedup) end) |
      .updated_at = $ts
    )
  end
  ' "$CAPABILITY_GENOME" > "$tmp" && mv "$tmp" "$CAPABILITY_GENOME"

echo "Capability genome updated: $capability_id"
