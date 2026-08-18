# Incident and Emergency-Stop Procedure

## When to stop outbound immediately

- A draft was approved in error and must not go out.
- The classifier is producing wrong/risky recommendations at volume.
- Meta reports a policy violation or account restriction.
- Any suspicion that `WHATSAPP_ACCESS_TOKEN` or `WHATSAPP_APP_SECRET` has leaked.

## Stop

From the phone or laptop:

```
forge-whatsapp stop
```

This writes `mode.outbound = "EMERGENCY_STOP"` to `whatsapp/config.json` synchronously.
`outbound.send()` re-reads this file on every call (never cached), so the very next send attempt after
`stop` is blocked with `BLOCKED_BY_AUTHORITY`, regardless of prior approvals. Inbound recording
(`OBSERVE`) continues so evidence isn't lost.

## If credentials leaked

1. Run `forge-whatsapp stop` immediately.
2. Rotate the app secret and access token in the Meta App Dashboard.
3. Update the environment variables wherever they're set (never in this repo).
4. Confirm the old token is rejected: an outbound attempt with the old token should fail with an HTTP
   401/403 from Meta, and `outbound.send()` will record the failure as `REVISION_REQUIRED` rather than
   `SAFE_AUTOMATION_EXECUTED`.

## Resuming

```
forge-whatsapp resume
```

This only ever returns the system to `DRAFT_ONLY` — never to a higher autonomy tier — matching the
mission's rule that autonomy increases require explicit, separate approval (`enable_higher_autonomy`
in the authority matrix), not just clearing a stop.

## Post-incident

Record what happened as an event using the existing repo convention:

```
./log_event.sh "whatsapp incident: <what happened, what was stopped, what was rotated>"
```

This writes to `events/events.log`, `memory/memory.log`, `consequences/consequences.log`, and
`world/world_state.log`, consistent with how every other incident in this system is captured.
