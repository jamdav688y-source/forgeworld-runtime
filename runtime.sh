#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"
DATE="$(date '+%Y-%m-%d %H:%M:%S')"

echo
echo "=== FORGEWORLD RUNTIME ==="
echo "TIME: $DATE"
echo

echo "CORE FLOW:"
echo "EVENT -> EVIDENCE -> MEMORY -> GOVERNANCE -> CONTINUITY -> CONSEQUENCE -> FUTURE_STATE"
echo

echo "INSTALLED MODULES:"
ls "$BASE" | sort
echo

echo "RECENT EVENTS:"
tail -5 "$BASE/events/events.log" 2>/dev/null
echo

echo "RECENT MEMORIES:"
tail -5 "$BASE/memory/memory.log" 2>/dev/null
echo

echo "RECENT CONSEQUENCES:"
tail -5 "$BASE/consequences/consequences.log" 2>/dev/null
echo

echo "WORLD STATE:"
tail -5 "$BASE/world/world_state.log" 2>/dev/null
echo

echo "DIAGNOSTIC:"
echo "Can the present world explain how it became itself?"
echo
