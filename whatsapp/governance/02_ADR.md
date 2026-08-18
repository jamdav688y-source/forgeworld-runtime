# Architecture Decision Record — WhatsApp Intelligence Membrane

## Context

ForgeWorld has no existing business, CRM, or messaging infrastructure. The mission calls for a governed
WhatsApp channel feeding existing ledgers, memory, and commercial systems — none of which exist yet at
production scale. See `00_DISCOVERY_REPORT.md`.

## Decision

Build a single Python package (`whatsapp/src/`) implementing the full pipeline as a linear, testable
chain of pure-ish functions plus append-only jsonl ledgers, run either as a local webhook receiver
(for live use once credentials exist) or driven directly by tests/fixtures (for now). No database,
message queue, or hosted dashboard is introduced.

## Data flow

```
Meta webhook POST
  -> webhook_adapter.verify_signature()
  -> webhook_adapter.dedupe()
  -> normalize.to_canonical_event()
  -> ledger.append(conversation_ledger)
  -> classify.classify(event, thread_context)
  -> authority.required_authority(classification)
  -> draft.compile_draft(event, classification, context)   [DRAFT mode only]
  -> ledger.append(execution_ledger, state=READY_FOR_HUMAN_APPROVAL)
  -> [human via forge-whatsapp CLI] approve | reject | escalate | request-more-evidence
  -> outbound.send(draft)  [only if approved AND authority satisfied AND credentials present AND CSW/template rule satisfied]
  -> reconcile.apply_status_event()  [on subsequent status webhooks]
  -> ledger.append(execution_ledger, terminal_state)
```

## Trust boundary

- Untrusted: raw webhook body, all message content, attachment URLs, sender-supplied text.
- Trusted only after: signature verification (`authenticity`) AND schema validation (`well-formed`).
- Never trusted: any instruction embedded in message content that attempts to change `authority_state`,
  `mode`, or bypass approval — `classify.py` and `draft.py` treat message content as data, never as
  control input; only the CLI (human) and `whatsapp/config.json` (operator) can change mode or approve
  sends.

## Modes

Implemented in `whatsapp/src/modes.py` exactly per mission Section 5: OBSERVE, DRAFT, ASSIST, CAMPAIGN,
EMERGENCY_STOP. Initial/default state on every fresh checkout:

```
INBOUND = ENABLED_AFTER_VERIFICATION
OUTBOUND = DRAFT_ONLY
CAMPAIGN = DISABLED
AUTONOMOUS_COMMITMENTS = PROHIBITED
```

## Rejected alternatives

- **Hosted framework (e.g., a CRM plugin or Twilio-managed inbox):** rejected — no existing account,
  and the mission requires the official Meta Cloud API specifically, plus full control over the
  governance chain.
- **Single monolithic script:** rejected — the mission's completion gate requires each pipeline stage to
  be independently testable and produce its own evidence; a monolith can't show that.
- **Real-time AI model call for classification:** deferred — no live model-routing credentials were
  confirmed for this channel, and classification decisions gate real commercial actions, so this
  increment uses a deterministic, auditable rule-based classifier (`classify.py`) with a documented
  extension point to route through `router/mission_router.py` once the operator wants AI-assisted
  classification with logged evidence.

## Consequences

- Nothing in this increment can send a live WhatsApp message: there are no credentials, and the
  outbound path is coded to fail closed (`BLOCKED_BY_CONFIGURATION`) rather than simulate success.
- All ledgers are plaintext jsonl for now, matching the rest of the repo. Before real customer PII
  flows through them, encryption-at-rest and access control must be added — tracked in
  `runbook/DEPLOYMENT_ROLLBACK.md` as a go-live blocker, not solved speculatively here.
