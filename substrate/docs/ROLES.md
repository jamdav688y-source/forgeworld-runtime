# Phone / Laptop Roles

Formalizes what the root `README.md` and `STATUS.md` already state for the
phone node, and defines the laptop's matching half. Both forges write into
the same substrate; neither owns a private, disconnected copy of the world.

## Laptop — primary execution forge

- Local reasoning and Claude Code development.
- Local model routing (any provider — see ARCHITECTURE.md on provider
  neutrality).
- Software generation, validation, documentation, media production, world
  simulation.
- Commercial packaging and mission archive management.
- Runs `process-queue.sh`, `new-mission.sh`, `update-mission.sh`,
  `validate-mission.sh`, `substrate-status.sh`.
- Prioritizes offline/local operation; cloud tools (Claude, GPT, etc.) are
  accelerators invoked during the `research`/`reason`/`build` phases, not
  dependencies of the substrate itself.

## Phone — mobile satellite forge

- Idea capture, voice notes, camera observations, screenshots, social post
  analysis (LinkedIn/Facebook), field notes, lightweight mission creation.
- Runs `capture-idea.sh` only — this requires no network and no laptop
  present. It is the phone's one substrate-writing action, and it is always
  available offline.
- Is a field intelligence node, not a passive client: every capture is a
  market/world signal the laptop will later turn into a mission.
- Syncs to the laptop whenever connectivity is available (git push/pull, or
  `scripts/forge-sync-pack.sh` for a tarball handoff).

## Division of labor at a glance

| Step in the lifecycle          | Phone | Laptop |
|---------------------------------|:-----:|:------:|
| Observe                         |  yes  |  yes   |
| Understand / Research / Reason  |       |  yes   |
| Build                           |       |  yes   |
| Validate / Govern                |       |  yes   |
| Package / Commercialize          |       |  yes   |
| Teach / Store                    |       |  yes   |
| Improve / Repeat                 |  yes  |  yes   |

The phone always contributes at the Observe and (eventually) Improve/Repeat
ends of the loop — it feeds signal in, and it is where the next captured
idea starts. The laptop carries the heavy middle of the loop.
