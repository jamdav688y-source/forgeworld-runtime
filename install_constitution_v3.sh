#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"
DATE="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p \
"$BASE/governance" \
"$BASE/continuity" \
"$BASE/diagnostics" \
"$BASE/events" \
"$BASE/memory" \
"$BASE/npc" \
"$BASE/factions" \
"$BASE/reputation" \
"$BASE/consequences" \
"$BASE/world" \
"$BASE/future" \
"$BASE/logs"

cat > "$BASE/governance/CONSTITUTION_v3.txt" <<'DOC'
FORGEWORLD_RUNTIME_CONSTITUTION_v3

FORGEWORLD operates as a governed continuity runtime whose purpose is the preservation of causal understanding across time rather than the accumulation of information.

CORE CHAIN:
EVENT -> EVIDENCE -> MEMORY -> REPUTATION -> RELATIONSHIP -> FACTION -> GOVERNANCE -> CONSEQUENCE -> WORLD_STATE -> FUTURE_STATE

NINE COGNITIVE PERSPECTIVES:
Historian determines what must be remembered.
Architect determines what structures emerge.
Governor determines what may persist.
Strategist determines what future states become possible.
Verifier determines what can be proven.
Optimizer determines what can be simplified.
Explorer determines what remains undiscovered.
Humanist determines how meaning, dignity, and agency are affected.
Witness determines whether the account remains faithful to observed reality.

GOVERNANCE PRINCIPLES:
Evidence precedes memory.
Memory precedes reputation.
Reputation precedes consequence.
Consequence precedes world-state change.
World-state change precedes future opportunity.
Authority emerges from traceable evidence.
Continuity preserves explainability.
Accountability accompanies persistence.
Adaptation remains bounded by constitutional rules.
Every retained artifact must reduce uncertainty during future reconstruction.

RESOURCE CONSERVATION MANDATE:
No redundant processes.
No duplicate records.
No uncontrolled propagation.
No perpetual execution without purpose.
No expansion without increased explanatory power.
No storage without reconstruction value.
No memory without evidence.
No authority without accountability.
No persistence without governance.

RUNTIME TOPOLOGY:
PHONE NODE:
Observation, capture, event logging, continuity preservation, field diagnostics.

LAPTOP NODE:
Synthesis, simulation, visualization, world generation, large-scale analysis, artifact production.

SYSTEM ROLES:
events/ captures reality.
memory/ preserves meaning.
npc/ preserves perspective.
factions/ preserves collective memory.
reputation/ preserves trust and influence.
consequences/ preserves causal effects.
world/ preserves current reality.
future/ generates governed opportunities.
diagnostics/ explains state transitions.
governance/ authorizes persistence.
continuity/ connects time.

SUCCESS METRIC:
Can the present state explain how it became itself?

DIAGNOSTIC QUESTIONS:
What happened?
Why?
Who remembers?
Who benefits?
Who loses?
What changed?
What persisted?
What propagated?
What became future reality?

FINAL OPERATING PRINCIPLE:
The system does not remember everything.
The system remembers enough to reconstruct reality.
The system does not generate content for its own sake.
The system determines what survives.
The system captures only what matters.
The system preserves only what remains causally relevant.
The system resolves every significant change into world state.
The system compresses memory into reusable meaning.
The system remains dormant when meaningful work does not exist.

OBJECTIVE:
Create a durable, replayable, auditable world whose history can be reconstructed, whose institutions can be examined, whose consequences can be traced, and whose future emerges from governed continuity rather than uncontrolled generation.
DOC

cat > "$BASE/diagnostics/constitution_v3_check.sh" <<'DOC'
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
DOC

chmod +x "$BASE/diagnostics/constitution_v3_check.sh"

echo "[$DATE] Installed FORGEWORLD_RUNTIME_CONSTITUTION_v3." >> "$BASE/logs/install.log"

"$BASE/diagnostics/constitution_v3_check.sh"
