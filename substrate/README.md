# ForgeWorld Continuity Substrate

This directory is the continuity substrate layer. It sits *around* the
existing ForgeWorld files (doctrine/, governance/, memory/, world/, the
Termux scripts in scripts/, and everything else at the repo root) without
overwriting any of them. Those files are the world's lore and phone-node
tooling; this directory is the working memory system that turns everything
phone and laptop do into reusable capability.

## Primary Law

Every completed operation must leave at least one reusable asset behind:
knowledge, code, workflow, evidence, prompt, template, design pattern,
commercial insight, governance record, or next action. `validate-mission.sh`
enforces this mechanically — a mission cannot be marked validated until it
has evidence, an artifact, an answered commercial question, and a next
recommended action.

## Layout

```
substrate/
  schema/
    mission.schema.json     JSON Schema for the shared mission package
    mission.template.json   Blank mission used when creating new missions
  missions/<mission_id>/
    mission.json             Structured source of truth
    mission.md                Human-readable, auto-generated view
  registries/
    mission_registry.json      one row per mission
    knowledge_registry.json    reusable knowledge/patterns/templates
    decision_registry.json     every decision, reviewable (Legitimacy Architecture)
    evidence_registry.json     every piece of evidence, linked to its mission
    prompt_registry.json       reusable prompts
    workflow_registry.json     reusable workflows
    commercial_registry.json   answers to "can this be sold/packaged?"
    asset_registry.json        every artifact created, of any kind
  capture/
    queue.jsonl               offline-safe phone/field capture queue
  scripts/
    lib.sh                    shared helpers (sourced by everything else)
    capture-idea.sh           PHONE: queue an observation, offline-safe
    process-queue.sh          LAPTOP: promote queued captures into missions
    new-mission.sh            LAPTOP: create a mission directly
    update-mission.sh         LAPTOP: append decisions/artifacts/evidence/etc.
    validate-mission.sh       Enforce the Primary Law on one mission
    substrate-status.sh       Real-state dashboard (no decoration)
  docs/
    ARCHITECTURE.md            knowledge graph model, lifecycle, provider neutrality
    ROLES.md                   phone vs laptop division of labor
```

## Quick start

Phone, offline, no laptop nearby:

```
substrate/scripts/capture-idea.sh --channel voice --text "client asked if we can turn the audit into a subscription" --tag commercial
```

This appends to `capture/queue.jsonl` and touches nothing else — it works
with no network and no laptop present. Sync the repo (git pull/push, or
`scripts/forge-sync-pack.sh` for a tarball) whenever connectivity returns.

Laptop, once the capture has synced in:

```
substrate/scripts/process-queue.sh
```

This turns every queued capture into a mission (with the raw capture
attached as evidence), ready for `understood -> researched -> reasoned ->
building -> validated -> governed -> packaged -> commercialized -> taught ->
stored` work via `update-mission.sh`.

Check real substrate state at any time:

```
substrate/scripts/substrate-status.sh
```

## Provider neutrality

Nothing in this directory names a specific model provider. Missions,
registries, and scripts operate purely on files and jq — any reasoning
engine (Claude, GPT, a local model, or a human with a text editor) can read
a mission, do the reasoning step, and write the result back with
`update-mission.sh`. The substrate owns memory, structure, evidence,
governance, and commercial intelligence; models are interchangeable
cognition, not infrastructure.
