# ADR-0002 — Signed header, separately hashed payload

**Status:** accepted · 2026-11-10

**Context.** The directive needs privacy classes, authorized deletion and per-device monotonic
sequences that sync cleanly. If an event's id covered its payload directly, withholding or
deleting a payload would break the hash chain and make the event unverifiable.

**Decision.** `event_id = H(header)`. The header contains `payload_hash`. Ed25519 signs the
event_id. Payloads can be WITHHELD (not cleared) or PURGED (deleted) while the header, the
signature and the per-device `prev` chain stay verifiable.

**Consequences.** Headers (type, links, timestamps, privacy class) are visible to every paired
peer, even for `DEVICE_LOCAL` events. Links use opaque hashed ids (`ct_…`), but metadata such as
"a message was recorded at time T" is shared. This is documented in LIMITATIONS.md.
