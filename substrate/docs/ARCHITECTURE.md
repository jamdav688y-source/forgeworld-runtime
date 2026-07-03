# Substrate Architecture

## Knowledge as a graph, not a pile of files

Every artifact created by a mission (`artifacts_created[]` in mission.json)
is registered in `asset_registry.json` with its `mission_id`. Every
decision, piece of evidence, prompt, workflow, and commercial opportunity is
likewise registered with a back-link to the mission that produced it. The
mission itself links forward and backward to predecessor/successor missions
via `links.predecessor_missions` / `links.successor_missions`.

This gives every artifact a traceable path:

```
artifact -> originating mission -> evidence -> reasoning (decisions)
         -> implementation (other artifacts) -> validation
         -> commercial value -> successor missions
```

You can walk this path with `jq` against the registries and mission files;
nothing is hidden in prose logs that only a human can parse.

## Lifecycle

Every mission moves through the same loop, tracked in
`mission.current_state`:

```
captured -> understood -> researched -> reasoned -> building -> validated
         -> governed -> packaged -> commercialized -> taught -> stored
         -> (complete, or spawns a successor mission and repeats)
```

`update-mission.sh MISSION_ID set-state STATE` advances a mission and stamps
the mission_registry with the same state, so the dashboard and the mission
file can never disagree about where a mission stands.

## Legitimacy architecture

A decision is only legitimate if it can be reviewed, reproduced, and
improved. `update-mission.sh ... add-decision` requires intent, evidence,
reasoning, and outcome; `alternatives_considered` and `lesson_learned` are
encouraged. `validate-mission.sh` fails a mission if any recorded decision
is missing intent/evidence/reasoning/outcome — an unreviewable decision is
treated as an incomplete mission.

## Commercial intelligence

Every mission is expected to answer, at minimum once: who benefits, what
problem this solves, whether it's sellable, and what packaging form it
could take (framework, template, diagnostic, service, product, article,
consulting offer, training asset, subscription, software feature, or IP).
This is stored via `update-mission.sh ... add-commercial` and mirrored into
`commercial_registry.json`, which is the substrate's running list of
monetizable capability — independent of which mission produced it.

## Provider neutrality

The substrate never invokes a specific AI provider directly. Scripts only
read/write JSON and Markdown. Any reasoning engine — Claude, Codex, a local
model, or a person — is expected to:

1. Read a mission (`mission.json` / `mission.md`).
2. Do the reasoning/build/validation step for the current lifecycle phase.
3. Write results back with `update-mission.sh`.

Swapping the model behind step 2 requires no change to the substrate.
