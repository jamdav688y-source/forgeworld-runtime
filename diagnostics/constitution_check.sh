#!/data/data/com.termux/files/usr/bin/bash

echo
echo "=== FORGEWORLD CONSTITUTION CHECK ==="
echo

test -f ~/forgeworld/governance/CONSTITUTION_v1.txt && echo "[OK] Constitution Present"

echo
echo "QUESTION:"
echo "Can the present state explain how it became itself?"
echo

echo "EVENTS:"
tail -5 ~/forgeworld/events/events.log 2>/dev/null

echo
echo "MEMORY:"
tail -5 ~/forgeworld/memory/memory.log 2>/dev/null

echo
echo "CONSEQUENCES:"
tail -5 ~/forgeworld/consequences/consequences.log 2>/dev/null

echo
echo "WORLD:"
tail -5 ~/forgeworld/world/world_state.log 2>/dev/null
