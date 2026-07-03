#!/usr/bin/env bash
# PHONE / FIELD CAPTURE
#
# Appends one capture to the offline queue (capture/queue.jsonl). This is the
# only thing the phone needs to be able to do without connectivity or a
# laptop nearby: observe the world and queue it. Nothing here requires
# network access. Sync happens later via git pull/push or forge-sync-pack.sh.
#
# Usage:
#   capture-idea.sh --channel voice --text "..." [--tag foo --tag bar]
#   capture-idea.sh                 (interactive prompt)
#
# Channels: voice, camera, screenshot, social, field-note, text, command

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

channel=""
text=""
tags=()

while [ $# -gt 0 ]; do
  case "$1" in
    --channel) channel="$2"; shift 2 ;;
    --text) text="$2"; shift 2 ;;
    --tag) tags+=("$2"); shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$channel" ]; then
  echo "Capture channel (voice/camera/screenshot/social/field-note/text/command):"
  read -r channel
fi
if [ -z "$text" ]; then
  echo "Enter what you observed/captured:"
  read -r text
fi

mkdir -p "$CAPTURE_DIR"
touch "$QUEUE_FILE"

capture_id="$(gen_id CAP)"
tags_json="$(printf '%s\n' "${tags[@]:-}" | jq -R . | jq -s 'map(select(length > 0))')"

entry="$(jq -nc \
  --arg capture_id "$capture_id" \
  --arg channel "$channel" \
  --arg raw_text "$text" \
  --arg captured_at "$(now_iso)" \
  --argjson tags "$tags_json" \
  '{capture_id: $capture_id, channel: $channel, raw_text: $raw_text, captured_at: $captured_at, tags: $tags, status: "queued", mission_id: null}')"

echo "$entry" >> "$QUEUE_FILE"

echo "Captured: $capture_id"
echo "Queued for laptop processing (run substrate/scripts/process-queue.sh)."
