# ForgeWorld WhatsApp Intelligence Membrane

A governed WhatsApp channel for ForgeWorld: webhook intake → authenticity check → normalization →
ledgering → classification → draft compilation → human approval → gated outbound → delivery
reconciliation. Built as the smallest complete pipeline sized to what actually exists in this repo
today — see `governance/00_DISCOVERY_REPORT.md` for what was reused vs. newly built and why.

**Current state: code-complete, never connected to live traffic.** No WhatsApp Business Platform
credentials exist yet. `OUTBOUND` defaults to `DRAFT_ONLY` and fails closed
(`BLOCKED_BY_CONFIGURATION`) without credentials. See `reports/claims_integrity_report.md` for exactly
what is and isn't true about this increment.

## Start here

- `governance/00_DISCOVERY_REPORT.md` — what exists, what was built, why
- `governance/01_PLATFORM_POLICY_EVIDENCE.md` — live-verified Meta platform rules (dated 2026-08-18,
  re-verify before go-live)
- `governance/02_ADR.md` / `03_THREAT_MODEL.md` / `04_PRIVACY_RETENTION_MODEL.md` /
  `05_AUTHORITY_MATRIX.md` — architecture and governance
- `runbook/OPERATIONS.md` — day-to-day phone commands
- `runbook/INCIDENT_EMERGENCY_STOP.md` — what to do if something goes wrong
- `runbook/DEPLOYMENT_ROLLBACK.md` — hard blockers before any live traffic, and how to go live
- `reports/evidence_package.md` — full end-to-end proof, test-by-test
- `reports/next_right_move.md` — what to actually do next

## Layout

```
whatsapp/
  config.json          mode + authority grants (safe defaults, no secrets)
  schemas/              versioned canonical event contract
  src/                  the pipeline itself (webhook_adapter, normalize, classify, draft,
                         approval, authority, outbound, reconcile, pipeline, cli, server, modes)
  ledgers/               runtime jsonl ledgers (gitignored -- real data once live)
  fixtures/              sanitized test payloads (no real numbers/tokens)
  tests/                 43 automated tests, no live network calls
  scripts/forge-whatsapp phone-first CLI entrypoint
  governance/            ADR, threat model, privacy model, authority matrix, policy evidence
  runbook/               operations, incident, deployment docs
  reports/                claims-integrity, evidence package, next-right-move
```

## Quick commands

```
./whatsapp/scripts/forge-whatsapp status
python3 -m unittest discover -s whatsapp/tests -p "test_*.py"
```
