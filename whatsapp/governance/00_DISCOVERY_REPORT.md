# Discovery Report — WhatsApp Intelligence Membrane

Date: 2026-08-18
Author: Claude Code, on behalf of the repository operator

## Canonical root

`jamdav688y-source/forgeworld-runtime`, branch `claude/forgeworld-whatsapp-membrane-sj47yn`.

## What FORGEWORLD is today

Per `doctrine/FORGEWORLD_RUNTIME.md`, `governance/CONSTITUTION_v3.txt`, and `STATUS.md`, FORGEWORLD is
a solo, personal "persistence-first RPG, simulation, world-building, and diagnostic engine" spanning
Phone (capture/observe/command) → Laptop (build/simulate) → GitHub (persist) → AI agents
(analyze/advise), with a LinkedIn-centered signal-acquisition loop. There is no product, no registered
storefront, and no customer base recorded anywhere in the repository as of this date.

The user has confirmed (via clarifying questions on this task) that ForgeWorld is intended to become a
**real, upcoming business**, that no WhatsApp Business Platform credentials exist yet, and that the
missing systems referenced by the mission brief should be built as **minimal new components sized to
what actually exists**, not as a full enterprise buildout.

## Inventory of existing components relevant to this mission

| Mission concept | Existing repo equivalent | Reuse decision |
|---|---|---|
| Conversation Ledger | none | New: `whatsapp/ledgers/conversation_ledger.jsonl`, append-only jsonl, same shape as `events/events.log` |
| Execution Ledger | none (`events/event_logger.txt` is a stub) | New: `whatsapp/ledgers/execution_ledger.jsonl` |
| Reality Learning / Reality Signal Engine | none (metaphorical only in `governance/CONSTITUTION_v3.txt`) | Not built. No aggregation/promotion engine exists to receive signals; a stub `whatsapp/ledgers/signal_ledger.jsonl` records raw signals for a *future* promotion engine, per the mission's own rule that no single message may modify architecture/pricing/capabilities without aggregated, independently validated evidence |
| Memory Buffer | `memory/memory.log`, `memory/memory_writer.txt` (empty stub) | Reused: WhatsApp draft compiler reads `memory/memory.log` as one context source; does not replace it |
| Capability registry / authority engine | `capabilities/registry.json` + `router/mission_router.py` — routes AI/tool capabilities for the operator's own tasks | Reused for AI-routing extension point only; **not** a business authority engine. A new, narrow `whatsapp/governance/authority_matrix.md` + `whatsapp/src/authority.py` implement the mission's send/commit authority rules, since the existing router has no concept of customer-facing consequence |
| Retrieval governance engine / evidence sufficiency gates | none | New, minimal: `whatsapp/src/classify.py` computes `evidence_sufficiency`; no retrieval-augmented system exists to govern, so this is a placeholder contract, not a real retrieval layer |
| Customer/contact records | none | New: `whatsapp/ledgers/consent_ledger.jsonl` doubles as the minimal contact/consent record; no CRM exists to integrate with |
| Offer/opportunity records | `future/future_opportunities.log` (personal opportunity journal) | New, narrow: `whatsapp/ledgers/opportunity_ledger.jsonl`; does not replace or repurpose the personal log |
| Notification system | none | Not built. Mission Control notification routing does not exist; escalation for now is a ledger flag surfaced by the CLI, not a push notification |
| Mission Control interface | none (only shell scripts under `scripts/`) | New: `whatsapp/scripts/forge-whatsapp`, a CLI following the existing `scripts/forge-*` naming and file-based-queue pattern |
| Phone/laptop bridge | described in doctrine only, no code | Not built. Out of scope for this increment — the CLI is phone-usable via Termux like the other `forge-*` scripts, which is the existing bridge mechanism |
| Prior WhatsApp/messaging/webhook/CRM code | none found repo-wide | Confirmed via full-repo search; nothing to extend |
| WhatsApp Business Platform credentials | none | Outbound adapter is credential-gated and returns `BLOCKED_BY_CONFIGURATION` until supplied |

## Design consequence

Because almost none of the assumed systems exist, this increment builds the **smallest complete
pipeline** end to end (webhook → authenticity → normalize → classify → draft → approve → send-gate →
reconcile → ledger → CLI) using flat jsonl ledgers consistent with the rest of the repository, rather
than standing up database services, message queues, or a hosted dashboard the operator has no
infrastructure for yet. Live sending stays disabled (`OUTBOUND=DRAFT_ONLY`) until real Meta credentials
are supplied and a human explicitly advances the mode — per the mission's completion gate.
