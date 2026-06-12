#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"
DATE="$(date '+%Y-%m-%d %H:%M:%S')"

EVENT="$*"

if [ -z "$EVENT" ]; then
  echo "Usage: ~/forgeworld/log_event.sh \"actor did action to target\""
  exit 1
fi

echo "[$DATE] EVENT: $EVENT" >> "$BASE/events/events.log"
echo "[$DATE] MEMORY_SEED: $EVENT created possible memory." >> "$BASE/memory/memory.log"
echo "[$DATE] CONSEQUENCE_SEED: $EVENT requires future-state evaluation." >> "$BASE/consequences/consequences.log"
echo "[$DATE] WORLD_PENDING: $EVENT has not yet been resolved into world state." >> "$BASE/world/world_state.log"

echo "EVENT INGESTED:"
echo "$EVENT"
echo
echo "Updated:"
echo "- events.log"
echo "- memory.log"
echo "- consequences.log"
echo "- world_state.log"
