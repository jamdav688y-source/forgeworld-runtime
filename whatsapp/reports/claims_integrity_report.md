# Claims-Integrity Report

Every claim below is checked against what actually exists in this increment, per the mission's rule
that technical capability must never be silently translated into assumed authority.

| Claim | Status | Basis |
|---|---|---|
| "WhatsApp is connected to ForgeWorld's Conversation Ledger" | **False as stated** | No such ledger existed; a new `conversation_ledger.jsonl` was built for this channel specifically (see discovery report). |
| "The system verifies webhook authenticity" | **True** | HMAC-SHA256 signature verification, tested against forged/wrong-secret/missing-header cases (`tests/test_webhook_adapter.py`). |
| "The system can send WhatsApp messages" | **False** | No live credentials exist. `outbound.send()` is fully implemented and tested against an injected transport, but has never made a real network call, and fails closed (`BLOCKED_BY_CONFIGURATION`) without credentials. |
| "Responses are AI-generated" | **False as stated** | Classification and drafting are deterministic, rule-based, and auditable in this increment — not model-generated. An extension point exists but is not wired (`classify.py` docstring). |
| "Human approval is required before any send" | **True** | Structurally enforced: `outbound.send()` requires an `APPROVED_AWAITING_SEND` execution-ledger entry written only by `approval.approve()`, which is only called from the CLI. Tested in `test_authority.py` and `test_outbound.py`, including a forged-approval-record case. |
| "The 24-hour customer service window is enforced" | **True** | `outbound._csw_open()` checks elapsed time since the conversation's last inbound message and requires a template outside the window; tested in `test_outbound.py`. |
| "Consent/opt-out is enforced" | **True** | Stop-word detection auto-revokes; revoked consent blocks sends (`test_consent.py`, `test_authority.py`). |
| "This has been tested against real Meta traffic" | **False** | All tests run against sanitized, fabricated fixtures. No live webhook has ever hit this code. |
| "This is production-ready" | **False** | Six hard blockers remain before go-live; see `runbook/DEPLOYMENT_ROLLBACK.md`. |

## What this increment does NOT claim

- It does not claim ForgeWorld has real customers, a real WhatsApp Business Platform account, or any
  commercial traction. The `future/future_opportunities.log` and `opportunity_ledger.jsonl` remain
  empty until real conversations happen.
- It does not claim any AI model was used to classify or draft messages.
- It does not claim compliance with any specific jurisdiction's privacy law — only that the mission's
  own permission-layer and retention-class model (Section 12) is implemented in code.
