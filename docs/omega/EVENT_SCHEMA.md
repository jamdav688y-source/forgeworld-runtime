# Canonical Event Schema — `fw.omega.event/1`

Source of truth: `omega/events.py` (validation) and `omega/policy.py` (who may write what).
A real event from the acceptance run: [`samples/event_sample.json`](samples/event_sample.json).

## Envelope

```json
{ "header": { … }, "signature": "<Ed25519 over event_id, base64url>", "payload": { … } | null }
```

`payload` is `null` when it is **WITHHELD** (the receiving peer is not cleared for its privacy
class) or **PURGED** (authorized deletion / retention). The header stays verifiable either way,
because the header binds the payload only by its hash.

## Header fields (all required, no others allowed)

| Field | Type | Meaning |
|---|---|---|
| `schema` | `"fw.omega.event/1"` | schema version; others are refused (`SCHEMA_UNSUPPORTED`) |
| `event_type` | enum | a key of `policy.EVENT_TYPES` |
| `device_id` | `dev_` + 32 hex | `sha256(Ed25519 public key)[:32]` of the writing device |
| `actor_id` | `"<kind>:<name>"` | who caused it: `human:…`, `model:…`, `tool:…`, `system:…` |
| `actor_kind` | `HUMAN \| MODEL \| TOOL \| SYSTEM` | must match the `actor_id` prefix |
| `seq` | int ≥ 1 | per-device monotonic sequence, no gaps |
| `prev` | event id \| null | the same device's `seq-1` event (hash chain); null only at seq 1 |
| `ts` | `YYYY-MM-DDTHH:MM:SSZ` | claimed capture time. Informational: **ordering never uses clocks** |
| `parents` | sorted unique event ids | causal predecessors (any device) |
| `payload_hash` | 64 hex | `sha256("forgeworld.omega.v1.payload\0" + canonical(payload))` |
| `artifacts` | sorted unique sha256 hex | original source artifacts (stored separately, raw bytes) |
| `provenance` | `[{kind, ref}]` | `kind ∈ source \| derived_from \| tool \| import` |
| `links` | sorted unique `"<entity>:<id>"` | identity / relationship links (`contact:…`, `deal:…`, `task:…`) |
| `privacy` | `PUBLIC < INTERNAL < PRIVATE < SECRET`, or `DEVICE_LOCAL` | sharing class; `DEVICE_LOCAL` payloads never leave the device |
| `scope` | enum | authorization scope, fixed per event type (`policy.EVENT_TYPES`) |
| `verification` | `UNVERIFIED \| VERIFIED \| CONTESTED \| REFUTED` | as asserted; non-humans may only write `UNVERIFIED` |
| `supersedes` | event id \| null | newer statement of the same thing |
| `corrects` | event id \| null | a correction; the original is never rewritten |

## Identity and hashing

* Canonical JSON = `cognition.cxp.canonical_bytes` (sorted keys, compact, UTF-8, **no floats**).
  Money is integer minor units; scores are integer per-mille.
* `event_id = "ev_" + sha256("forgeworld.omega.v1.event\0" + canonical(header))`.
* Domain separation (`event`, `payload`, `receipt`, `state`, `conflict`, `contact`, …) means two kinds
  of object can never share an identifier.
* `signature = Ed25519(device signing key, event_id as ASCII)`. Ed25519 is deterministic.

## Governance rules enforced at validation

* Actor kinds per event type are a closed table (`policy.EVENT_TYPES`). Human-only:
  `TASK_AUTHORIZED`, `PROMOTION_DECISION`, `DELETION_AUTHORIZED`, `RETENTION_POLICY`,
  `CONFLICT_RESOLVED`, `PAYMENT_VERIFIED`, `PEER_PAIRED`, `ACCESS_REVOKED`, `PROJECT_ASSERTED`,
  `COMMITMENT_STATUS`.
* Scope `governance` is human-only, whatever the event type.
* **Operator attestation** (`omega/operator.py`): `TASK_AUTHORIZED`, `DELETION_AUTHORIZED`,
  `PAYMENT_VERIFIED`, `PROMOTION_DECISION`, `RETENTION_POLICY`, `PEER_PAIRED` and `ACCESS_REVOKED`
  (`policy.ATTESTED_TYPES`) carry `payload._operator = {operator_id, sig}`, where `sig` is
  Ed25519 by the device's passphrase-unlocked operator key over
  `H("operator-attestation", {event_type, device_id, actor_id, payload without _operator})`. The
  actor must be `human:<operator name>`. `append()` refuses these types without the unlocked key.
  Effects (purge, revocation, retention, payment confirmation, task execution) apply only if the
  attestation verifies against the operator registered for the writing device. An unattested one
  is kept as history and quarantined `UNATTESTED_*`.
* `TASK_AUTHORIZED.authorized_device` must equal the writer's `device_id` (authorization is local).
* `MESSAGE_RECORDED` must cite a `source`; `WRITTEN_AGREEMENT` and `PAYMENT_VERIFIED` must carry
  an artifact; `DELIVERABLE_ACCEPTED` must cite a customer-originated source.
* `PEER_PAIRED` / `ACCESS_REVOKED` are always `DEVICE_LOCAL`.

## Storage rules (`omega/store.py`)

* `events` rows: no DELETE (trigger); no UPDATE of identity, header, signature, order, origin
  (trigger). The only allowed change is to the payload column: `WITHHELD → PRESENT` (backfill;
  the hash is checked in code) or `→ PURGED`.
* `receipts`: no UPDATE, no DELETE (triggers).
* Original artifacts: table `artifacts` (raw bytes, content-addressed); derived text: events + FTS.
* **Authorized deletion** = a human `DELETION_AUTHORIZED` event: purges the target's payload, its
  FTS rows and any artifact no other live event uses; keeps the header. Deletions sync like any
  event, so peers purge too.
* **Retention** = a human `RETENTION_POLICY` (event type, max age in days); `apply_retention()`
  purges deterministically on every node that holds the policy.
* **Access revocation** = `ACCESS_REVOKED` (local): the peer can no longer sync, and events it
  originated are refused.

## Event types

`ARTIFACT_INGESTED, NOTE_RECORDED, PROJECT_ASSERTED, CONTACT_ASSERTED, MESSAGE_RECORDED,
FACT_ASSERTED, COMMITMENT_RECORDED, COMMITMENT_STATUS, DRAFT_PRODUCED, COMMERCE_SIGNAL,
PAYMENT_VERIFIED, TASK_QUEUED, TASK_AUTHORIZED, TASK_RESULT, PEER_PAIRED, ACCESS_REVOKED,
DELETION_AUTHORIZED, RETENTION_POLICY, CONFLICT_RESOLVED, BENCHMARK_RESULT, AGENT_OPINION,
EXPERIMENT_RECORDED, PROMOTION_DECISION`. Payload schemas: `events._check_payload`.

## Receipts — `fw.omega.receipt/1`

`{schema, type, device_id, index, prev, subjects, state_before, state_after, detail}`;
`receipt_id = "rc_" + sha256(domain "receipt", body)`, signed by the device. There is no
wall-clock time in the body, so the same device applying the same transitions produces
byte-identical receipts (`test_receipts.py`). `state_*` = digest of {per-device vector, purged ids}.
Samples: [`samples/receipts_phone.json`](samples/receipts_phone.json),
[`samples/receipts_pc.json`](samples/receipts_pc.json).
