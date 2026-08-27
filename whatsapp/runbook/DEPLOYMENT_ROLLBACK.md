# Deployment and Rollback

## Current state (this increment)

- `INBOUND = ENABLED_AFTER_VERIFICATION`, `OUTBOUND = DRAFT_ONLY`, `CAMPAIGN = DISABLED`,
  `AUTONOMOUS_COMMITMENTS = PROHIBITED` — the mission's mandated default (`whatsapp/config.json`).
- No live Meta credentials exist. Nothing in this codebase can send a live WhatsApp message yet.
- All 43 automated tests pass against sanitized fixtures; no live network call is made by the test
  suite (`http_post` is dependency-injected in every outbound test).

## Hard blockers before any live traffic (must be resolved by the operator, not assumed away)

1. Meta Business verification and WhatsApp Business Platform onboarding for ForgeWorld.
2. Legal/privacy review of `governance/04_PRIVACY_RETENTION_MODEL.md` against applicable law for
   wherever customers are located.
3. Encryption at rest for the ledgers once they hold real PII (not implemented in this increment —
   see `governance/02_ADR.md` consequences).
4. Malware/type/size validation for real media attachments (deferred — no live media pipeline to test
   against yet).
5. Hosting for `whatsapp/src/server.py` behind TLS, reachable by Meta's webhook delivery infrastructure.
6. At least one approved message template registered in the Meta Business Manager, for sends outside
   the 24h customer service window.

## Deploying (once the above are resolved)

1. Set `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`,
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ID_SALT` in the host environment.
2. Run `python3 -m whatsapp.src.server` behind a TLS-terminating reverse proxy.
3. Register the webhook URL + verify token in the Meta App Dashboard; confirm the GET handshake
   succeeds (`governance/01_PLATFORM_POLICY_EVIDENCE.md`).
4. Send one real test message from a personal WhatsApp account to the business number; confirm it
   appears in `conversation_ledger.jsonl` with `authority_state: observe` and nothing is sent back
   automatically (`OUTBOUND` is still `DRAFT_ONLY`).
5. Only after reviewing real evidence in `execution_ledger.jsonl`, consider moving individual actions
   from `DRAFT_ONLY` toward `ASSIST_LOW_RISK` — one narrowly-scoped action at a time, each requiring its
   own `authority.grants[]` entry per `governance/05_AUTHORITY_MATRIX.md`. `CAMPAIGN` stays `DISABLED`
   until a documented opt-in/audience/budget process exists, which does not exist yet.

## Rollback

- `forge-whatsapp stop` — immediate, reversible, no deploy needed (see
  `INCIDENT_EMERGENCY_STOP.md`).
- To fully roll back the code: this is a self-contained subtree (`whatsapp/`) that reads/writes only
  its own `config.json` and `ledgers/`; deleting or reverting the directory does not touch any other
  part of the repository. Ledgers are append-only and gitignored, so rolling back the code never
  deletes evidence already captured on disk.
