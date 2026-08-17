# Pocket Cortex Architecture

## What this upgrade actually changed

The prior implementation (branch `claude/pocket-cortex-title-screen-hvf7j8`)
was a real, working, well-built visual shell — the awakening screen, the
constellation intent-router, and the Demonstrate mode script are all
preserved verbatim in this upgrade — but everything past the visual
layer was explicitly labeled as what it was: `STATE_ITEMS` was a
hardcoded constant (`KNOWLEDGE: 0.72, EVIDENCE: 0.58, CREATIVITY: 0.84,
EXECUTION: 0.66, CLARITY: 0.91`), the workspace tag said `DEMO CONTENT`,
and `state.history` was an in-memory array that vanished on reload.
There was no backend, no persistence, and no concept of authority
distinct from capability anywhere in the code.

This upgrade adds all of that without touching the honest parts that
were already there.

## The governing chain, mapped to real code

```
INTENT                  -> goal text entered in the UI
CONTEXT                 -> lib/context.js: checkContext() verifies the
                            mission id / capability / route nodes a
                            request claims actually exist in this
                            server's own state before anything downstream runs
EVIDENCE QUALIFICATION   -> lib/governance.js EvidenceState + lib/db.js
                            evidence_records table
MISSION                  -> lib/db.js missions table (persistent, not
                            in-memory)
CAPABILITY CHECK        -> lib/capability.js: checkCapability() -- is
                            this technically reachable right now
                            (python3 on PATH, script file present, or
                            "this running process" for built-ins)
AUTHORITY CHECK          -> lib/governance.js: evaluateAuthority() --
                            is this actor permitted, right now, given
                            this specific context
EXECUTION                -> lib/api.js executeCapabilityHandler() --
                            only reached after both checks above pass
VERIFICATION              -> the one capability with a real side effect
                            (RUN_RECONCILE_SCAN) records its actual
                            stdout as evidence, not an assumed success
MEMORY                    -> lib/db.js execution_attempts +
                            routing_decisions + evidence_records,
                            all persistent, all queryable via HISTORY
NEXT-RIGHT-MOVE            -> lib/nextMove.js: generateNextMove(),
                            recomputed from real state after every
                            mutation
```

No stage infers a downstream answer from an upstream pass -- concretely:
`capability_available` never causes an authority check to be skipped
(`lib/api.js::executeCapabilityHandler` checks capability, then
independently checks authority); a bounded-authority `ALLOWED_BOUNDED`
decision is not `ALLOWED` (the two are distinct enum values threaded all
the way to the UI's gate badges); and a successful `EXECUTE` never
implies a promotion — this app doesn't currently expose a promotion
concept in the UI at all, deliberately, rather than fake one.

## Why `node:sqlite`, not `better-sqlite3`

Zero npm dependencies means zero `npm install` step, which matters
specifically on Termux: no network dependency to install a native
module, no native compilation toolchain requirement (`better-sqlite3`
ships prebuilt binaries per platform/arch and falls back to
compiling from source when none matches — Android/Termux is exactly
the kind of environment that often needs the from-source fallback,
which needs a C++ toolchain most Termux installs don't have by
default). `node:sqlite` is Node's own built-in module (stable as of
Node 22.5, still flagged experimental by the runtime itself as of this
writing) — already present in any `node` binary capable of running this
app at all, no separate install step, ever.

**Honesty note on provenance:** no prior `node:sqlite` or
`better-sqlite3` code was found anywhere in this repository or any of
its branches before this upgrade — this is a new choice made to satisfy
the mission's explicit instruction, not a preservation of prior art that
turned out not to exist in git.

## Truthful indicators — the exact methodology

`lib/indicators.js` documents each formula inline; summarized:

| Indicator | Computed from | Honest limitation |
|---|---|---|
| **Knowledge** | count of routing decisions + evidence records, saturating at 1 | accumulation proxy, not depth of understanding |
| **Evidence** | the mission's strongest qualified `EvidenceState`, mapped 0–1 | the most literal of the five — it *is* the evidence ladder |
| **Creativity** | count of distinct capability-route combinations explored | **explicitly labeled a proxy in the API response** (`isProxy: true`) — route diversity is not a quality judgment, and the UI shows it as one |
| **Execution** | success ratio of recorded execution attempts | zero attempts is 0, never an optimistic default |
| **Clarity** | margin between the top-scored and second-scored capability in the latest routing pass | measures routing confidence, not goal quality |

Every indicator ships a `basis` string in the API response, and the UI
shows it as a tooltip — "truthful" here means *inspectable*, not
"objectively correct." Nothing is fabricated to look more precise than
what it actually is.

## Capability ≠ Authority, structurally

`lib/capability.js` and `lib/governance.js` are separate files on
purpose. `checkCapability("TRIGGER_PHONE_DEPLOY")` can be `true` (the
script exists, `python3` is on PATH) while `evaluateAuthority
("TRIGGER_PHONE_DEPLOY")` is unconditionally `REQUIRES_APPROVAL` — the
two are never derived from each other anywhere in the code.

**Honest limitation, stated plainly:** the Python `governance/` module
(branch `claude/forgeworld-authority-separation`, not merged to `main`)
models *multiple* actors and enforces decider identity server-side.
Pocket Cortex is a single-user, single-device local tool — there is no
second party to check an actor's identity against. A `REQUIRES_APPROVAL`
decision here is enforced as a UI confirmation step and a static policy
table with no API route that can reach it, not as cryptographic proof of
who clicked a button. That still achieves the thing that matters — a
reachable capability is never silently treated as an authorized one —
through interaction friction and code-path absence rather than identity
verification. See `lib/governance.js`'s own top-of-file comment for the
same disclosure in the source.

## Self-escalation guard

`MODIFY_CAPABILITY_POLICY` is `HUMAN_ONLY` in the policy table, and the
policy table itself (`lib/governance.js`'s `POLICY` object) is a `const`
with no API route, no database row, and no code path that writes to it
at runtime. Changing it requires editing the source file and restarting
the process — which is what "human-only" means when there's no second
actor to distinguish by identity: it means a human at a keyboard, not a
running request handler.

## Known scope boundaries (not implemented, not pretended)

- No promotion/release-lifecycle concept exposed in the UI — nothing to
  fake here, so nothing was added.
- `RUN_RECONCILE_SCAN` is the only capability with a real side effect
  beyond this server's own database; every other capability's "success"
  is bookkeeping about this server's own state.
- The client's `KEYWORD_MAP` duplicate (for instant as-you-type
  preview) can, in principle, drift from `lib/routing.js`'s server copy
  if one is edited without the other — documented directly in both
  files' comments, and the server is authoritative for anything
  persisted.
