#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"
DATE="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p \
"$BASE/memory" \
"$BASE/reputation" \
"$BASE/relationships" \
"$BASE/factions" \
"$BASE/council_reviews" \
"$BASE/consequences" \
"$BASE/world" \
"$BASE/future" \
"$BASE/diagnostics" \
"$BASE/logs"

cat > "$BASE/governance/PHASE_5_RUNTIME.txt" <<'DOC'
FORGEWORLD_PHASE_5_RUNTIME

PURPOSE:
Convert passive storage into active meaning.

PRIMARY FLOW:
EVENT -> MEMORY -> REPUTATION -> RELATIONSHIP -> FACTION -> COUNCIL -> CONSEQUENCE -> WORLD -> FUTURE -> EVENT

RESOURCE LAW:
Do not run loops.
Do not poll continuously.
Do not execute background processes.
Act only when manually invoked.
Remain dormant when no meaningful event exists.

MODULE QUESTIONS:
EVENT asks: What happened?
MEMORY asks: Who remembers?
REPUTATION asks: Who is affected?
RELATIONSHIP asks: Who trusts whom?
FACTION asks: Who benefits or loses?
COUNCIL asks: What do the nine perspectives conclude?
CONSEQUENCE asks: What changes?
WORLD asks: What became true?
FUTURE asks: What is now possible?

SUCCESS:
A single event propagates through every layer and produces a traceable world-state update.
DOC

cat > "$BASE/resolve_event.sh" <<'DOC'
#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"
DATE="$(date '+%Y-%m-%d %H:%M:%S')"
EVENT="$*"

if [ -z "$EVENT" ]; then
  echo "Usage: ~/forgeworld/resolve_event.sh \"event description\""
  exit 1
fi

echo "[$DATE] EVENT: $EVENT" >> "$BASE/events/events.log"

echo "[$DATE] MEMORY: The world remembers that $EVENT." >> "$BASE/memory/memory.log"

echo "[$DATE] REPUTATION: Reputation requires evaluation after: $EVENT." >> "$BASE/reputation/reputation.log"

echo "[$DATE] RELATIONSHIP: Relationships may shift because: $EVENT." >> "$BASE/relationships/relationships.log"

echo "[$DATE] FACTION: Factions must evaluate benefit, loss, and alignment after: $EVENT." >> "$BASE/factions/faction_memory.log"

echo "[$DATE] COUNCIL_REVIEW:" >> "$BASE/council_reviews/council.log"
echo "Historian: What must be remembered from $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Architect: What structure changed after $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Governor: What is permitted to persist after $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Strategist: What future states became possible after $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Verifier: What evidence proves $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Optimizer: What can be simplified after $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Explorer: What remains undiscovered after $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Humanist: How were meaning and dignity affected by $EVENT?" >> "$BASE/council_reviews/council.log"
echo "Witness: Does the account remain faithful to observed reality?" >> "$BASE/council_reviews/council.log"

echo "[$DATE] CONSEQUENCE: $EVENT generated a consequence proposal requiring governance." >> "$BASE/consequences/consequences.log"

echo "[$DATE] WORLD_STATE: $EVENT is now a resolved world-state candidate." >> "$BASE/world/world_state.log"

echo "[$DATE] FUTURE: New opportunities may emerge from $EVENT." >> "$BASE/future/future_opportunities.log"

echo
echo "FORGEWORLD EVENT RESOLVED THROUGH PHASE 5:"
echo "$EVENT"
echo
echo "Flow completed:"
echo "EVENT -> MEMORY -> REPUTATION -> RELATIONSHIP -> FACTION -> COUNCIL -> CONSEQUENCE -> WORLD -> FUTURE"
echo
DOC

chmod +x "$BASE/resolve_event.sh"

cat > "$BASE/diagnostics/phase5_check.sh" <<'DOC'
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
DOC

chmod +x "$BASE/diagnostics/phase5_check.sh"

echo "[$DATE] Installed PHASE_5_RUNTIME active meaning layer." >> "$BASE/logs/install.log"

echo "PHASE 5 RUNTIME INSTALLED."
echo
echo "Test with:"
echo "~/forgeworld/resolve_event.sh \"Player defeated Crystal Warden in the northern ruins\""
echo "~/forgeworld/diagnostics/phase5_check.sh"
