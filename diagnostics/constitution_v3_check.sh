#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"

echo
echo "=== FORGEWORLD CONSTITUTION v3 CHECK ==="
echo

test -f "$BASE/governance/CONSTITUTION_v3.txt" && echo "[OK] Constitution v3 present" || echo "[MISSING] Constitution v3"

echo
echo "CORE QUESTION:"
echo "Can the present state explain how it became itself?"

echo
echo "RECENT EVENTS:"
tail -5 "$BASE/events/events.log" 2>/dev/null

echo
echo "RECENT MEMORY:"
tail -5 "$BASE/memory/memory.log" 2>/dev/null

echo
echo "RECENT CONSEQUENCES:"
tail -5 "$BASE/consequences/consequences.log" 2>/dev/null

echo
echo "WORLD STATE:"
tail -5 "$BASE/world/world_state.log" 2>/dev/null

echo
echo "CONSTITUTION PATH:"
echo "$BASE/governance/CONSTITUTION_v3.txt"
echo
