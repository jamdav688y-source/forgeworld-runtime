#!/usr/bin/env bash
# LAPTOP (or phone with jq): apply one lifecycle update to a mission and
# fan it out to the matching registry, so the mission and the graph never
# drift apart.
#
# Usage:
#   update-mission.sh MISSION_ID set-state STATE
#   update-mission.sh MISSION_ID set-next-action "TEXT"
#   update-mission.sh MISSION_ID add-constraint "TEXT"
#   update-mission.sh MISSION_ID add-acceptance-criterion "TEXT"
#   update-mission.sh MISSION_ID add-lesson "TEXT"
#   update-mission.sh MISSION_ID add-artifact TYPE "DESCRIPTION" [PATH]
#   update-mission.sh MISSION_ID add-decision INTENT EVIDENCE REASONING OUTCOME [ALTERNATIVES] [LESSON]
#   update-mission.sh MISSION_ID add-validation METHOD RESULT
#   update-mission.sh MISSION_ID add-commercial WHO_BENEFITS PROBLEM_SOLVED SELLABLE(true|false) PACKAGING_FORM [NOTES]
#   update-mission.sh MISSION_ID link-successor SUCCESSOR_MISSION_ID
#
# Every subcommand regenerates mission.md and updates the mission_registry
# timestamp, so `git status` always reflects exactly what changed.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

mission_id="${1:?mission_id required}"; shift
cmd="${1:?subcommand required}"; shift
json_path="$(require_mission "$mission_id")"
ts="$(now_iso)"

update_json() {
  local filter="$1"; shift
  local tmp; tmp="$(mktemp)"
  jq "$@" "$filter" "$json_path" > "$tmp" && mv "$tmp" "$json_path"
}

touch_registry_mission() {
  local state="$1"
  local reg; reg="$(registry_path mission)"
  local tmp; tmp="$(mktemp)"
  jq --arg mid "$mission_id" --arg state "$state" --arg ts "$ts" \
    '(.entries[] | select(.mission_id == $mid)) |= (.current_state = $state | .updated_at = $ts) | .updated_at = $ts' \
    "$reg" > "$tmp" && mv "$tmp" "$reg"
}

case "$cmd" in
  set-state)
    state="${1:?state required}"
    update_json '.current_state = $s | .updated_at = $ts' --arg s "$state" --arg ts "$ts"
    touch_registry_mission "$state"
    ;;

  set-next-action)
    text="${1:?text required}"
    update_json '.next_recommended_action = $t | .updated_at = $ts' --arg t "$text" --arg ts "$ts"
    ;;

  add-constraint)
    text="${1:?text required}"
    update_json '.constraints += [$t] | .updated_at = $ts' --arg t "$text" --arg ts "$ts"
    ;;

  add-acceptance-criterion)
    text="${1:?text required}"
    update_json '.acceptance_criteria += [$t] | .updated_at = $ts' --arg t "$text" --arg ts "$ts"
    ;;

  add-lesson)
    text="${1:?text required}"
    update_json '.lessons_learned += [$t] | .updated_at = $ts' --arg t "$text" --arg ts "$ts"
    ;;

  add-artifact)
    type="${1:?type required}"; desc="${2:?description required}"; path="${3:-}"
    id="$(gen_id AST)"
    update_json '.artifacts_created += [{asset_id: $id, type: $type, description: $desc, path: $path}] | .updated_at = $ts' \
      --arg id "$id" --arg type "$type" --arg desc "$desc" --arg path "$path" --arg ts "$ts"
    append_registry_entry asset "$(jq -n --arg id "$id" --arg mission_id "$mission_id" --arg type "$type" --arg desc "$desc" --arg path "$path" --arg ts "$ts" \
      '{asset_id: $id, mission_id: $mission_id, type: $type, description: $desc, path: $path, created_at: $ts}')"
    if [ "$type" = "knowledge" ] || [ "$type" = "design_pattern" ] || [ "$type" = "template" ]; then
      append_registry_entry knowledge "$(jq -n --arg id "$id" --arg mission_id "$mission_id" --arg type "$type" --arg desc "$desc" --arg ts "$ts" \
        '{knowledge_id: $id, mission_id: $mission_id, type: $type, description: $desc, created_at: $ts}')"
    fi
    if [ "$type" = "prompt" ]; then
      append_registry_entry prompt "$(jq -n --arg id "$id" --arg mission_id "$mission_id" --arg desc "$desc" --arg path "$path" --arg ts "$ts" \
        '{prompt_id: $id, mission_id: $mission_id, description: $desc, path: $path, created_at: $ts}')"
    fi
    if [ "$type" = "workflow" ]; then
      append_registry_entry workflow "$(jq -n --arg id "$id" --arg mission_id "$mission_id" --arg desc "$desc" --arg path "$path" --arg ts "$ts" \
        '{workflow_id: $id, mission_id: $mission_id, description: $desc, path: $path, created_at: $ts}')"
    fi
    ;;

  add-decision)
    intent="${1:?intent required}"; evidence="${2:?evidence required}"; reasoning="${3:?reasoning required}"
    outcome="${4:?outcome required}"; alternatives="${5:-}"; lesson="${6:-}"
    id="$(gen_id DEC)"
    update_json '.decisions_made += [{decision_id: $id, intent: $intent, evidence: $evidence, reasoning: $reasoning, constraints: "", alternatives_considered: $alt, validation: "", outcome: $outcome, lesson_learned: $lesson}] | .updated_at = $ts' \
      --arg id "$id" --arg intent "$intent" --arg evidence "$evidence" --arg reasoning "$reasoning" \
      --arg alt "$alternatives" --arg outcome "$outcome" --arg lesson "$lesson" --arg ts "$ts"
    append_registry_entry decision "$(jq -n --arg id "$id" --arg mission_id "$mission_id" --arg intent "$intent" \
      --arg evidence "$evidence" --arg reasoning "$reasoning" --arg outcome "$outcome" --arg lesson "$lesson" --arg ts "$ts" \
      '{decision_id: $id, mission_id: $mission_id, intent: $intent, evidence: $evidence, reasoning: $reasoning, outcome: $outcome, lesson_learned: $lesson, created_at: $ts}')"
    ;;

  add-validation)
    method="${1:?method required}"; result="${2:?result required}"
    id="$(gen_id VAL)"
    update_json '.validation_results += [{validation_id: $id, method: $method, result: $result, validated_at: $ts}] | .updated_at = $ts' \
      --arg id "$id" --arg method "$method" --arg result "$result" --arg ts "$ts"
    ;;

  add-commercial)
    who="${1:?who_benefits required}"; problem="${2:?problem_solved required}"
    sellable="${3:?sellable true|false required}"; form="${4:?packaging_form required}"; notes="${5:-}"
    id="$(gen_id COM)"
    update_json '.commercial_opportunities += [{commercial_id: $id, who_benefits: $who, problem_solved: $problem, sellable: ($sellable == "true"), packaging_form: $form, notes: $notes}] | .updated_at = $ts' \
      --arg id "$id" --arg who "$who" --arg problem "$problem" --arg sellable "$sellable" --arg form "$form" --arg notes "$notes" --arg ts "$ts"
    append_registry_entry commercial "$(jq -n --arg id "$id" --arg mission_id "$mission_id" --arg who "$who" \
      --arg problem "$problem" --arg sellable "$sellable" --arg form "$form" --arg notes "$notes" --arg ts "$ts" \
      '{commercial_id: $id, mission_id: $mission_id, who_benefits: $who, problem_solved: $problem, sellable: ($sellable == "true"), packaging_form: $form, notes: $notes, created_at: $ts}')"
    ;;

  link-successor)
    successor="${1:?successor mission_id required}"
    update_json '.links.successor_missions += [$s] | .updated_at = $ts' --arg s "$successor" --arg ts "$ts"
    if [ -f "$(mission_json_path "$successor")" ]; then
      succ_tmp="$(mktemp)"
      jq --arg p "$mission_id" '.links.predecessor_missions += [$p]' "$(mission_json_path "$successor")" > "$succ_tmp"
      mv "$succ_tmp" "$(mission_json_path "$successor")"
      render_mission_md "$successor"
    fi
    ;;

  *)
    echo "Unknown subcommand: $cmd" >&2
    exit 1
    ;;
esac

render_mission_md "$mission_id"
echo "Updated $mission_id ($cmd)"
