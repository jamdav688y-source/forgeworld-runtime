# Operations Runbook

## Daily / on-demand phone workflow

```
forge-whatsapp status           # channel health, mode, pending count
forge-whatsapp review           # list drafts awaiting approval
forge-whatsapp approve <draft_id> --actor "<you>" --note "..."
forge-whatsapp reject <draft_id> --actor "<you>" --note "..."
forge-whatsapp escalate <draft_id> --actor "<you>" --note "..."
forge-whatsapp request-more-evidence <draft_id> --actor "<you>"
forge-whatsapp mark-not-opportunity <draft_id> --actor "<you>"
forge-whatsapp schedule-follow-up <draft_id> --actor "<you>" --follow-up-at "2026-08-25T09:00:00Z"
forge-whatsapp stop              # EMERGENCY STOP -- disables outbound immediately
forge-whatsapp resume            # resume in DRAFT_ONLY (never auto-resumes higher)
```

## Required environment variables (not set by default -- OUTBOUND stays BLOCKED_BY_CONFIGURATION until set)

| Variable | Purpose |
|---|---|
| `WHATSAPP_APP_SECRET` | HMAC key for verifying inbound webhook signatures |
| `WHATSAPP_VERIFY_TOKEN` | Shared secret for the GET webhook subscription handshake |
| `WHATSAPP_ACCESS_TOKEN` | Meta Graph API bearer token, required to send |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta-assigned phone number ID, required to send |
| `WHATSAPP_ID_SALT` | Salt for hashing raw phone numbers into pseudonymous `contact_id` |

None of these are committed anywhere in this repo. Set them in your shell/host environment or a
secret manager before running `whatsapp/src/server.py`.

## Running the webhook receiver

```
cd forgeworld-runtime
python3 -m whatsapp.src.server   # binds 127.0.0.1:8443 by default
```

Point Meta's webhook configuration at a reverse proxy/tunnel in front of this process (not built here
-- no hosting infrastructure exists yet for this operator). The GET verification handshake and POST
signature verification are both implemented; see `governance/01_PLATFORM_POLICY_EVIDENCE.md`.

## Running the test suite

```
python3 -m unittest discover -s whatsapp/tests -p "test_*.py" -v
```

## Reviewing evidence

- `whatsapp/ledgers/conversation_ledger.jsonl` — every authenticated inbound/status event.
- `whatsapp/ledgers/execution_ledger.jsonl` — full state trace per draft (READY_FOR_HUMAN_APPROVAL →
  APPROVED_AWAITING_SEND → terminal state), plus blocked attempts.
- `whatsapp/ledgers/consent_ledger.jsonl` — consent history per contact.
- `whatsapp/config.json` — current mode and authority grants.
