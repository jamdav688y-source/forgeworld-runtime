# Pocket Cortex — FORGEWORLD's governed mobile command deck

A phone-first cognitive shell: describe an intent, watch it route to a
capability, work it through a governed lifecycle (INTENT → ROUTE → WORK →
REVIEW → NEXT), and get one concrete next-right-move back — with every
mutating action passing through the same governing chain:

```
INTENT → CONTEXT → EVIDENCE QUALIFICATION → MISSION → CAPABILITY CHECK
→ AUTHORITY CHECK → EXECUTION → VERIFICATION → MEMORY → NEXT-RIGHT-MOVE
```

**Capability ≠ Authority ≠ Evidence ≠ Promotion.** Every one of those is
a separate, real check in this codebase, not a single boolean. See
[`docs/POCKET_CORTEX_ARCHITECTURE.md`](../docs/POCKET_CORTEX_ARCHITECTURE.md)
for exactly how.

## Quick start (any machine with Node 22.5+)

```bash
cd pocket-cortex
./start.sh            # serves http://127.0.0.1:8080
```

No `npm install` — the whole backend is `node:sqlite` + `node:http` +
`node:test`, zero third-party dependencies, by design (see the
architecture doc for why that matters on Termux specifically).

## Deploying to an actual phone

Not the same as running it locally for development — see
[`docs/POCKET_CORTEX_DEPLOYMENT.md`](../docs/POCKET_CORTEX_DEPLOYMENT.md)
for the exact Termux command, what it checks before touching anything,
and the Android smoke-test checklist.

## Layout

```
pocket-cortex/
├── index.html / styles.css / app.js   the client — constellation UI,
│                                        Demonstrate mode, offline states
├── server.js                          zero-dependency HTTP server
├── lib/
│   ├── db.js                          node:sqlite persistence
│   ├── governance.js                  capability/authority policy
│   ├── capability.js                  capability-availability checks
│   ├── context.js                     CONTEXT-chain integrity check
│   ├── routing.js                     intent → capability routing
│   ├── indicators.js                  Knowledge/Evidence/Creativity/
│   │                                    Execution/Clarity, truthfully
│   ├── nextMove.js                    next-right-move generation
│   └── api.js                         request handlers
├── tests/                             node --test suite (77 tests)
├── data/                              pocket-cortex.db lives here —
│                                        gitignored, never deployed over
├── manifest.webmanifest / sw.js       PWA installability + offline shell
└── start.sh                           local launcher
```

## Running the tests

```bash
cd pocket-cortex
node --test
```

## Privacy note

Demonstrate mode (the "DEMONSTRATE" button) is entirely scripted, canned
text — it never calls the API, never creates a mission, and never reads
or writes `data/pocket-cortex.db`. Nothing shown during a demo is
persisted anywhere.
