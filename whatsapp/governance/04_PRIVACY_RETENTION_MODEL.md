# Privacy and Retention Model

## Permission layers (mission Section 12)

The system distinguishes six permissions explicitly, tracked per-contact in `consent_ledger.jsonl`:

| Permission | Field | Default |
|---|---|---|
| Receive | `can_receive` | true once a user messages the business number (implicit under WhatsApp's own opt-in-to-business rule) |
| Store | `can_store` | true (required to operate at all); revocable via delete request |
| Analyze | `can_analyze` | true; classification only, no third-party sharing |
| Respond | `can_respond` | true within CSW; template-gated outside it |
| Recontact | `can_recontact` | false until explicit campaign opt-in is recorded (mission Section 5, CAMPAIGN disabled by default) |
| Use as business evidence | `can_use_as_evidence` | true for the specific conversation only; aggregation into `signal_ledger.jsonl` strips direct identifiers (contact_id is pseudonymous, not the raw phone number) |

## Contact identity

Raw phone numbers are hashed (SHA-256, salted with `WHATSAPP_ID_SALT`) into `contact_id` at the
normalization boundary (`normalize.py`). The raw number is retained only in `consent_ledger.jsonl`
(the minimal contact record) under `retention_class: contractual`, not in the conversation or signal
ledgers.

## Retention classes

| Class | Meaning | Applied to |
|---|---|---|
| `ephemeral` | Deleted after processing; not written to durable ledger | Failed/malformed events after trace capture window (see runbook) |
| `operational` | Kept while the conversation is active | `conversation_ledger.jsonl` entries |
| `contractual` | Kept per opt-in/consent record and applicable law | `consent_ledger.jsonl` |
| `evidence` | Kept as durable business evidence, pseudonymized | `signal_ledger.jsonl`, `opportunity_ledger.jsonl` |

## Deletion / opt-out

- Stop-word handling (`STOP`, `UNSUBSCRIBE`, etc., case-insensitive) is detected in `classify.py` and
  immediately sets `consent_state=revoked` and `can_recontact=false` in the consent ledger — this is a
  safe, low-risk automatic action per the mission's authority matrix (Section 11).
- A revoked contact's future inbound events still get authenticity-checked and ledgered (`OBSERVE`
  never turns off for safety/evidence reasons) but never receive automated or drafted outbound content.
- `forge-whatsapp delete-contact <contact_id>` removes the contact's raw phone number from the consent
  ledger and redacts `content_reference` fields for that contact's conversation-ledger entries, leaving
  a tombstone record (`{"redacted": true, "event_id": ..., "redacted_at": ...}`) so the ledger's
  append-only audit property is preserved without retaining the deleted content.

## Encryption

Not implemented in this increment (no live PII flows yet — see ADR consequences). Flagged as a hard
go-live blocker in `runbook/DEPLOYMENT_ROLLBACK.md`.
