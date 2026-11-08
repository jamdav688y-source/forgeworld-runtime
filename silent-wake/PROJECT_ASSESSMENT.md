# The Silent Wake — Phase One Assessment

Status: Repository analysis complete. No game implementation has started. This document is the record required before any code is written.

## 0. Headline finding

`forgeworld-runtime` is not a game engine, an "intelligence substrate," or a software platform with connectors, UI, orchestration, or packaging. It is a **63-file personal productivity and journaling system**, designed to run from a phone (Termux) and a laptop, that uses RPG/governance language as a metaphor for tracking the repo owner's own ideas, tasks, and reputation-building activity (e.g. LinkedIn networking). Concretely:

- Every `.sh` script does one of: append a line to a `.log` file, `cat` a doctrine file, or `tar` up markdown notes. None render anything, run a game loop, resolve combat, or manage assets.
- `governance/`, `doctrine/`, `consequences/`, `reputation/`, `relationships/`, `factions/`, `council_reviews/` contain **prose specifications of a philosophy**, not implementations. E.g. `consequences/consequence_engine.txt` says a consequence "must define... rollback possibility" — there is no code that defines, stores, or evaluates a consequence object anywhere in the repo.
- `rpg/player.json` and `world/world_state.json` describe the repo owner as a level-1 "Civilization Architect" tracking real-life resources (Knowledge, Trust, Influence). This is the user's own gamified life-tracking, not CRPG game state.
- `quests/active_quests.md` lists real tasks ("Connect phone and laptop through GitHub"), not in-fiction quests.
- The one piece of game-flavored content in the whole repo is a single log line: `Player defeated Crystal Warden in the northern ruins.` — an example string typed once into `resolve_event.sh`, not a combat system.
- There is no UI code, no rendering, no asset files (art/audio/models), no save/load system beyond flat-file logs, no dialogue tree format, no combat resolution logic, no build/packaging scripts for any distributable target, and no connector code integrating any third-party service (Slack/Airtable/etc. exist as tools available to *me*, the assistant, in this session — they are not part of this repository).

This changes the shape of the mission. The instruction was "integration before expansion" — I searched exhaustively (every file in the repo, listed below) before concluding that for a CRPG, there is close to nothing at the code level to integrate. What *is* worth carrying forward is conceptual, not architectural, and I call that out explicitly in section 2.

## 1. Full repository map (all 63 tracked files)

| Area | Contents | Reality |
|---|---|---|
| Root docs (`README.md`, `README.txt`, `STATUS.md`, `TASKS.md`, `CAPTURE.md`) | Phone-node role description, current task list | Personal ops notes for the repo owner |
| `doctrine/` (5 files, 2 empty) | `FORGEWORLD_RUNTIME.md`, `FORGEWORLD_CIVILIZATION_RUNTIME_v2.md` + 3 empty stubs (`governance.md`, `identity.md`, `linkedin_protocol.md`) | Mission statements / metaphor, no logic |
| `governance/` (7 files) | `CONSTITUTION_v1/v3`, `EVOLUTION_DIRECTIVE_v1`, `FORGEWORLD_RUNTIME_v2`, `PHASE_5_RUNTIME`, `NEXT_PHASE` (empty), `master_persistence_directive` | Iterative drafts of the same "event→evidence→memory→reputation→consequence→world-state→future" philosophy |
| `events/`, `memory/`, `consequences/`, `reputation/`, `relationships/`, `factions/`, `council_reviews/`, `future/` | Mostly a `*.txt` spec file describing what the module *should* do, plus a `.log` file that a shell script appends plain text to | No parsing, no schema enforcement, no relationships between records beyond string concatenation |
| `world/` | `world_state.json`, `world_state.log`, `world_state.txt` (spec) | Toy JSON with empty arrays; log is just appended strings |
| `rpg/player.json` | One JSON object | Repo owner's own "character sheet," not a player-character system |
| `npc/`, `npcs/` | `npc_memory.txt` (spec) + `network.md` (3 real people: LinkedIn contacts) | No NPC data model; "network.md" is literally the user's professional network |
| `quests/active_quests.md` | 6 checkboxes | Real dev tasks, not game quests |
| `diagnostics/` (4 files) | Shell scripts that `tail` log files and echo a fixed philosophical question | Health-check scripts for the phone workflow |
| `scripts/` (8 files: `forge`, `forge-world`, `forge-signal`, `forge-status.sh`, `forge-capture.sh`, `forge-clean.sh`, `forge-log.sh`, `forge-sync-pack.sh`) | Interactive Termux CLI (`forge status/capture/event/npc/quest/review/sync/archive/map/doctrine/clean`) | A personal CLI journal tool, Termux-specific (`#!/data/data/com.termux/...` shebang) |
| `install_*.sh` (3 files) | Heredoc scripts that write the spec `.txt` files and `log_event.sh`/`runtime.sh` into place | Idempotent installers for the above, nothing more |
| `commands/FORGE_COMMANDS.md` | Command glossary for the phone workflow | Docs |
| `inbox/capture.md`, `notes/observations.md` (empty), `logs/install.log` | Raw capture log | Personal notes |

Nothing outside this table exists. There is no `src/`, no `assets/`, no `ui/`, no `client/`, no `server/`, no build config (`package.json`, `.csproj`, `project.godot`, `Cargo.toml`, etc.), and no CI.

## 2. Integration Report (per the requested checklist)

| System | Requested | Found | Verdict |
|---|---|---|---|
| Dialogue | reusable dialogue system | none | Build new |
| Combat | reusable combat system | one flavor-text log line, no rules/logic | Build new |
| UI | reusable UI | none (no rendering framework anywhere in the repo) | Build new |
| Saves | reusable save/load | append-only `.log`/`.json` files, no load/replay logic, no versioning | Not directly reusable as an engine save system, but the **pattern** (event log → derived state) is a legitimate design for an investigation/memory-log mechanic — see below |
| State/world model | reusable state machine | `world_state.json` is a static, mostly-empty snapshot; no transition logic | Build new |
| Quests | reusable quest system | a markdown checklist of real-life tasks | Build new |
| Cinematics | reusable cinematic/cutscene tooling | none | Build new |
| Packaging | reusable build/export pipeline | none (installers only write text files) | Build new |
| Launcher | reusable game launcher | none (`forge` is a Termux journaling CLI, not a game launcher) | Build new |
| Assets | reusable art/audio/models | none | Build new |
| Observability | reusable logging/telemetry for a shipped game | `diagnostics/*.sh` just `tail` text logs for the dev's own workflow | Not applicable to a shipped product; build a real client-side error/telemetry approach if needed later |
| Validation | reusable QA/test framework | none | Build new |

**Conclusion:** there is no code-level foundation to build the CRPG on top of. Every one of the ten systems the mission calls out (dialogue, combat, UI, saves, state, quests, cinematics, packaging, launcher, assets) starts at zero.

**What genuinely is worth reusing — conceptually, not as code:**
1. **The causal chain (`Event → Evidence → Memory → Reputation → Consequence → World State`)** is, unintentionally, a well-formed design for exactly the mechanic *The Silent Wake* needs: a ship where "memory inconsistencies slowly emerge" and "evidence begins contradicting recollection." I'd adapt this as the game's **Investigation/Memory Log system** — every clue is an Event, every crew recollection is a Memory that can be flagged as contradicted by Evidence, and Reputation/Trust tracks how much the party believes each crewmate. That's a genuine design asset extracted from the doctrine, not a coincidence I'd want to throw away.
2. **The "Council of Minds" archetypes** (Historian, Architect, Governor, Strategist, Verifier, Optimizer, Explorer, Humanist, Witness) are a usable lens for writing NPC personalities or an in-fiction advisory mechanic, if the design ever wants one.
3. **Naming and tone** — "ForgeWorld" as the internal production codename, "The Silent Wake" as the product name — already established and consistent with the mission brief.
4. **Repo/branch conventions and this GitHub remote** — real and reusable as infrastructure (version control, PR flow).

Everything else — the shell scripts, the JSON stubs, the log files — is workflow tooling for the repo owner's personal system and should stay exactly where it is, untouched, doing its job. It is not something the game reads from or writes to at runtime.

## 3. Connector Report

The mission asked me to inventory "every connector already represented" before recommending new ones. I did not find any software connectors in this repository — no API clients, no webhook handlers, no third-party SDK usage, no auth config. The "nodes" described in the doctrine (Phone / Laptop / GitHub / AI / LinkedIn) are **workflow roles for a human**, not integrations a game calls at runtime:

- **Phone (Termux)**: where the owner captures ideas via `forge capture`.
- **Laptop**: where "heavy builds" happen (per `README.md`: "This phone is not the heavy build engine. The laptop builds.").
- **GitHub**: version control / persistence, which this session already uses.
- **AI (ChatGPT/Codex/Claude)**: governance/review/build assistance — i.e., this collaboration itself.
- **LinkedIn**: the owner's personal networking signal source, unrelated to gameplay.

None of these are things *The Silent Wake*, as a shipped single-player CRPG, needs to call at runtime. A commercial CRPG for Steam/itch/Epic does not need a Slack, Airtable, or LinkedIn connector — those would be scope creep, not integration.

**Recommendation:** add zero new connectors, and don't try to wire game code into the phone/journal workflow. The only "connector" this project needs is the existing Git/GitHub flow already in use for source control, which is already working.

## 4. Directory Recommendation

Create the game as a sibling of the doctrine/governance content, not inside it, so the two systems (personal ops tooling vs. shipped product) never collide:

```
forgeworld-runtime/
├── (existing doctrine/governance/scripts — untouched)
└── silent-wake/                  ← new, the entire CRPG lives here
    ├── PROJECT_ASSESSMENT.md     ← this document
    ├── game/                     ← engine project (once engine is chosen)
    ├── design/                   ← GDD, narrative bible, encounter/quest specs
    ├── art/                      ← source art (concept, portraits, environment)
    └── build/                    ← export presets / packaging config per storefront
```

Rationale: `silent-wake/` is self-contained, so the eventual Steam/itch/Epic build pipeline only ever needs to zip/export that one directory — nothing from `governance/`, `events/`, `memory/`, etc. should ship inside the game, since none of it is game data (it's the developer's personal journal). This also directly satisfies "players should never see ForgeWorld": ForgeWorld's own directories are physically outside the shipped game's folder.

## 5. Engine decision — blocking question

Nothing in this repository specifies a game engine, rendering framework, or language. This is the one decision I should not make silently, because it determines the entire `game/` directory structure, every subsequent implementation step, and the commercialization path (Steam/itch/Epic all differ in export friction and licensing by engine). I'm asking before scaffolding anything.

My recommendation, given the stated art direction (painterly, cinematic, readable) and commercial goal (small solo/indie team, Steam+itch+Epic): **Godot 4**. It's free with no royalties or revenue thresholds (unlike Unity's runtime fee model and Unreal's 5% royalty above $1M), has first-party 2D/2.5D support well suited to painterly hand-authored environments, exports natively to Steam/itch/Epic, and keeps a solo-friendly build size and iteration speed.

## 6. Vertical Slice Plan (bounded — nothing beyond this list)

Scope, once engine is confirmed:

1. **Title screen** — logo, painterly key art, New Game / Continue / Options.
2. **One ship, one deck** — a single explorable merchant-ship deck (galley, cargo hold, quarters, deck rail) built as a hand-authored space, not a generator.
3. **Four Level 1 party members** — stat blocks, portraits, one idle/reactive barks each.
4. **One crew interaction** — a scripted dialogue scene establishing normalcy, with one embedded inconsistency the player can notice.
5. **One investigation** — using the Evidence/Memory/Contradiction pattern pulled from the doctrine (section 2.1): the player gathers 2–3 pieces of evidence that contradict a crew member's stated memory.
6. **One combat encounter** — single scripted fight (not systemic/proc-gen) demonstrating core combat rules.
7. **One cinematic reveal** — the alien vessel appearing on the horizon; a scripted camera/transition sequence, not a cutscene engine.
8. **Save/load** — one save slot, serializing party state, deck state, and investigation flags.
9. **Title → Slice → Reveal → back to Title** as a complete, closed loop.

Explicitly out of scope for v1, per the mission's own constraint: no MMO systems, no procedural/infinite world generation, no generalized AI framework, no large content library. This slice is meant to prove *quality of experience* in ~15–30 minutes of playable content, not breadth.

## 7. Commercialization posture

- Godot exports directly to Windows/Mac/Linux builds suitable for Steamworks, itch.io butler upload, and the Epic Games Store — no engine-level licensing renegotiation needed later, since Godot has no revenue-share tier to graduate out of.
- Keep `silent-wake/build/` holding per-storefront export presets from day one (even before the first slice is done), so "commercial release" is a configuration target, not a rearchitecture.
- Store page assets (key art, capsule images) should come from the same painterly art pipeline as in-game portraits/environments — one visual pipeline, multiple outputs — rather than a separate marketing-art track.

## 8. Prioritized roadmap (smallest demonstrable milestone first)

| # | Milestone | Player value | Effort | Depends on |
|---|---|---|---|---|
| 1 | Engine scaffold + title screen with placeholder art | Low visible value, but unblocks everything | Low | Engine decision (§5) |
| 2 | One deck, walkable, with painterly placeholder environment art | First "this feels like a game" moment | Medium | 1 |
| 3 | Four party members with portraits + one dialogue scene (normalcy) | Establishes tone and cast | Medium | 2 |
| 4 | Investigation mechanic: evidence vs. memory contradiction, 2–3 clues | This *is* the game's hook — highest value-to-effort of the whole slice | Medium | 3 |
| 5 | One scripted combat encounter | Proves the action-RPG half of "Action RPG/CRPG" | Medium-High | 3 |
| 6 | Save/load for the slice | Required for any real playtesting | Low-Medium | 2–5 |
| 7 | Cinematic reveal (alien vessel) | Payoff moment, highest emotional impact per second of content | Medium-High (needs camera/transition tooling) | 2, 4 |
| 8 | Steam/itch/Epic export presets + store-page-ready capture | Turns the slice into something shareable/demoable externally | Low | 1–7 |

Recommended immediate next step after this document: confirm the engine (§5), then build milestone 1–2 as the first executable commit.
