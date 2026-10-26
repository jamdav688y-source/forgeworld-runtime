# Architecture Maturity Router

ForgeWorld selects the least-complex architecture capable of completing a
mission safely. Framework and provider preference do not determine the level.

## Levels

1. `simple_chatbot`
2. `rag_application`
3. `single_agent`
4. `multi_agent_system`
5. `autonomous_workflow`
6. `enterprise_agent`

Mission properties determine the minimum required level. Evidence maturity
sets the maximum authority that may be granted:

| Evidence | Maximum level |
| --- | ---: |
| none | 1 |
| hypothesis | 2 |
| prototype | 3 |
| validated | 5 |
| operational | 6 |

When the required level exceeds the evidence cap, routing returns
`evidence_blocked`. When mandatory controls are absent, it returns
`control_blocked`. Neither state authorizes execution.

Consequential actions require `human_approval`. Autonomous workflows require
`validation` and `recovery`. Enterprise agents additionally require
`observability`, `audit_log`, `cost_tracking`, and `access_control`.

## Example

```bash
python3 router/mission_router.py \
  --objective "Run a monitored multi-agent research mission" \
  --tags research,analysis \
  --parallel-specialists \
  --evidence-level validated \
  --requested-level 4
```

The architecture assessment is written into the same mission decision record
as capability routing. Existing callers that do not provide architecture
context receive `not_assessed_missing_context` with execution authorization
set to false.
