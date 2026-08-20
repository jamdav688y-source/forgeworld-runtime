# FW-AGENT-MESH-005 — Governed Cross-Session Transport

Status: `IMPLEMENTED_NOT_TRANSPORT_VERIFIED`  
Promotion: `NOT_ELIGIBLE`

Claude Code v2.1.224+ can discover and exchange plain-text messages with
other Claude Code sessions. ForgeWorld treats that vendor feature as a
transport candidate, not as authority, orchestration, evidence, or proof of
execution.

This package adds the missing system layer:

1. stable session identity and declared capability classes;
2. content hashes, mission lineage, causation and idempotency;
3. TTL, maximum hops, queue bounds and duplicate quarantine;
4. `ACCEPT_BOUNDED`, `HOLD_FOR_REVIEW`, `REFUSE`, and `QUARANTINE` dispositions;
5. a sequential `REQUEST -> ACKNOWLEDGED -> AUTHORITY_CHECKED -> EXECUTING -> EVIDENCE_ATTACHED -> REVIEWED -> CLOSED` protocol;
6. an invariant that transport receipt always returns `execute: false`.

No Claude-specific socket or remote API is called by this implementation.
The adapter remains deliberately transport-neutral until a compatible
Claude Code runtime is available for a bounded integration probe.

Same-machine socket delivery and cross-machine relay must be recorded as
different trust boundaries (`LOCAL_SOCKET` versus `REMOTE_RELAY`). The
receiving session's permission settings remain authoritative. A message
cannot approve a permission prompt, change settings, execute its embedded
text, or promote its own result.

Completion requires a later execution proof showing: two identified test
sessions, bounded message delivery, ledger preservation, duplicate rejection,
expiry behavior, and a result that cannot close without evidence.
