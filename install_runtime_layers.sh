#!/data/data/com.termux/files/usr/bin/bash

BASE="$HOME/forgeworld"
DATE="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p \
"$BASE/state" \
"$BASE/events" \
"$BASE/memory" \
"$BASE/npc" \
"$BASE/factions" \
"$BASE/reputation" \
"$BASE/consequences" \
"$BASE/world" \
"$BASE/diagnostics" \
"$BASE/logs"

cat > "$BASE/events/event_logger.txt" <<'EOL'
EVENT LOGGER

Purpose:
Capture every meaningful action before it becomes memory.

Every event must record:
- timestamp
- actor
- action
- target
- location
- evidence
- affected NPCs
- affected factions
- reputation change
- consequence seed
- world-state change

Rule:
No event becomes history until it has evidence.
No evidence becomes memory until governance accepts it.
EOL

cat > "$BASE/memory/memory_writer.txt" <<'EOL'
MEMORY WRITER

Purpose:
Convert events into usable memory.

Memory is not raw storage.
Memory is compressed causal meaning.

Every memory must answer:
- what happened
- why it mattered
- who remembers it
- what changed after it
- what future behavior it may influence

Memory talks to:
- NPC memory
- faction memory
- reputation system
- consequence engine
- world state
EOL

cat > "$BASE/npc/npc_memory.txt" <<'EOL'
NPC MEMORY

Purpose:
Give every character personal continuity.

Each NPC stores:
- personal events witnessed
- trust toward player
- fear
- loyalty
- grudges
- debts
- rumors heard
- faction pressure
- contradiction points
- future behavioral bias

NPC memory feeds reputation.
Reputation feeds faction judgment.
Faction judgment feeds world state.
World state reshapes NPC behavior.
EOL

cat > "$BASE/factions/faction_memory.txt" <<'EOL'
FACTION MEMORY

Purpose:
Let groups remember differently than individuals.

Each faction stores:
- collective history
- allies
- enemies
- territorial claims
- moral code
- institutional trauma
- economic pressure
- political goals
- remembered betrayals
- remembered victories

Faction memory converts individual action into institutional consequence.
EOL

cat > "$BASE/world/world_state.txt" <<'EOL'
WORLD STATE

Purpose:
Represent the current reality of the simulation.

World state tracks:
- active regions
- open conflicts
- closed conflicts
- faction power
- economic conditions
- discovered locations
- destroyed locations
- unlocked routes
- forbidden zones
- historical turning points

World state is the visible result of:
events
memory
governance
reputation
consequences
continuity
EOL

cat > "$BASE/reputation/reputation_system.txt" <<'EOL'
REPUTATION SYSTEM

Purpose:
Translate behavior into social consequence.

Reputation is not popularity.
Reputation is remembered behavioral evidence.

Track:
- trust
- fear
- honor
- suspicion
- usefulness
- danger
- reliability
- betrayal risk
- faction alignment
- public legend

Reputation changes how NPCs respond.
NPC responses create new events.
New events reshape memory.
Memory reshapes the world.
EOL

cat > "$BASE/consequences/consequence_engine.txt" <<'EOL'
CONSEQUENCE ENGINE

Purpose:
Convert actions into delayed world effects.

Each consequence must define:
- immediate effect
- delayed effect
- hidden effect
- affected NPCs
- affected factions
- affected locations
- reputation impact
- future-state mutation
- rollback possibility

Rule:
A consequence that does not change future state is not a consequence.
EOL

cat > "$BASE/diagnostics/system_interweave.txt" <<'EOL'
FORGEWORLD INTERWEAVE LAW

EVENT LOGGER captures what happened.
MEMORY WRITER compresses why it mattered.
NPC MEMORY personalizes the event.
FACTION MEMORY institutionalizes the event.
REPUTATION SYSTEM socializes the event.
CONSEQUENCE ENGINE propagates the event.
WORLD STATE reveals what survived.

The system is circular:

EVENT
-> EVIDENCE
-> MEMORY
-> NPC MEMORY
-> FACTION MEMORY
-> REPUTATION
-> CONSEQUENCE
-> WORLD STATE
-> FUTURE EVENT

Diagnostic question:
Can the present world explain how it became itself?
EOL

cat > "$BASE/log_event.sh" <<'EOL'
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
EOL

chmod +x "$BASE/log_event.sh"

cat > "$BASE/runtime.sh" <<'EOL'
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
EOL

chmod +x "$BASE/runtime.sh"

echo "[$DATE] Installed event logger, memory writer, NPC memory, faction memory, world state, reputation system, and consequence engine." >> "$BASE/logs/install.log"

echo "FORGEWORLD runtime layers installed."
echo
"$BASE/runtime.sh"
