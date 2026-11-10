# ADR-0006 — External actions need a human authorization on the executing device

**Status:** accepted · 2026-11-10

**Decision.** Task definitions are shared evidence. Execution state is device-local. A task with
an external effect (declared by the task OR its executor; the stricter wins) runs only when this
device holds a `TASK_AUTHORIZED` event written LOCALLY by a HUMAN actor for that exact task
event. Sync never calls the executor. An external task interrupted mid-run goes to NEEDS_REVIEW
and is never retried automatically. Unknown actions are refused.

**Consequences.** Authorizing on the phone does not let the PC act (test proves it). A human must
authorize on the device that will act. This is deliberate friction, matching rule 9.
