#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"

echo
echo "=== FORGEWORLD PHASE 5 CHECK ==="
echo

echo "FLOW:"
echo "EVENT -> MEMORY -> REPUTATION -> RELATIONSHIP -> FACTION -> COUNCIL -> CONSEQUENCE -> WORLD -> FUTURE"
echo

echo "RECENT EVENT:"
tail -1 "$BASE/events/events.log" 2>/dev/null

echo
echo "RECENT MEMORY:"
tail -1 "$BASE/memory/memory.log" 2>/dev/null

echo
echo "RECENT REPUTATION:"
tail -1 "$BASE/reputation/reputation.log" 2>/dev/null

echo
echo "RECENT RELATIONSHIP:"
tail -1 "$BASE/relationships/relationships.log" 2>/dev/null

echo
echo "RECENT FACTION:"
tail -1 "$BASE/factions/faction_memory.log" 2>/dev/null

echo
echo "RECENT COUNCIL:"
tail -10 "$BASE/council_reviews/council.log" 2>/dev/null

echo
echo "RECENT CONSEQUENCE:"
tail -1 "$BASE/consequences/consequences.log" 2>/dev/null

echo
echo "RECENT WORLD:"
tail -1 "$BASE/world/world_state.log" 2>/dev/null

echo
echo "RECENT FUTURE:"
tail -1 "$BASE/future/future_opportunities.log" 2>/dev/null

echo
echo "QUESTION:"
echo "Can the present world explain how it became itself?"
echo
