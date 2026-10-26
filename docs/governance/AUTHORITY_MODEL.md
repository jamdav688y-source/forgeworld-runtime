# AUTHORITY_MODEL.md

**Mission:** FORGEWORLD-AUTHORITY-SEPARATION-001
**Status:** DESIGNED -> IMPLEMENTED -> TESTED -> VERIFIED (see RELEASE_REPORT section at the bottom). Not yet promoted to constitutional/core status -- that decision belongs to a human, per this mission's own release-discipline instruction.

## The law this document exists to enforce

> **CAPABILITY ≠ AUTHORITY ≠ EVIDENCE ≠ PROMOTION**

Before this mission, ForgeWorld had exactly one of these four concepts
implemented in code: **capability**. `capabilities/registry.json` +
`capabilities/discover.py` answer "is this tool reachable right now?" --
a pure technical-possibility question, measured by probing a command,
an env var, a TCP connection, or marking something as always-reachable
(`self`) or manually-confirmed. `router/mission_router.py` then routes a
mission to whichever reachable capability scores best on fit and cost.

Nowhere in that path does anything ask "is this actor *permitted* to use
this capability, for this specific target, right now?" Reachability was
functioning as permission. That is precisely the anti-pattern this
mission's brief names explicitly:

```python
if actor.has_tool:
    execute()
```

`capabilities/discover.py`'s own `probe_all()` is not that anti-pattern
by itself -- it correctly limits itself to reachability. The anti-pattern
was the *absence* of anything else: no downstream code ever asked a
second, different question before executing. This governance layer is
that second question, made explicit, typed, and enforced.

## The incident that forced the distinction

`git push origin NRM-v0.1-CLASSROOM` returned HTTP 403, immediately after
`git push -u origin claude/next-right-move-pwa-t0h6p5` (a branch push)
succeeded with the same session credentials, the same remote, the same
process. Capability (git installed, network reachable, credentials
present) was identical for both operations. The *outcome* differed. The
only explanation that fits the evidence is that these are two distinct
capabilities with two distinct authority postures -- not one
"repository write" capability that either works or doesn't. Full case
writeup: [`docs/evidence/NRM_TAG_403_CASE.md`](../evidence/NRM_TAG_403_CASE.md).

## The four concepts, defined

**CAPABILITY** -- can this actor/system technically perform this
operation? Answered by `capabilities/discover.py` (reachability) and,
separately, by the `capability_available` flag passed into
`governance.pipeline.run_pipeline()`. Says nothing about permission.

**AUTHORITY** -- is this actor permitted to perform this *specific*
operation, in this scope, right now? Answered exclusively by
`governance.authority.evaluate_authority()`. Never inferred from
capability. Never inferred from a different capability's authority, even
a related one (see "External trust boundaries" below).

**EVIDENCE** -- what has actually been observed/verified about the world
as a result of an attempted or completed operation? Answered by
`governance.evidence`, using a five-state vocabulary (`UNKNOWN`,
`OBSERVED`, `SUPPORTED`, `VALIDATED`, `INSTITUTIONALIZED`) adapted --
not invented -- from the staged-strength language already in
`governance/EVOLUTION_DIRECTIVE_v1.txt` ("No memory becomes reputation
until multiple observations reinforce it") and the `EVENT -> EVIDENCE ->
MEMORY -> REPUTATION -> ...` chain in `governance/CONSTITUTION_v3.txt`.
Execution succeeding produces evidence; it is not itself evidence of
anything beyond "this one attempt produced this one result."

**PROMOTION** -- may the resulting state/artifact advance to a higher
lifecycle tier? Answered exclusively by `governance.promotion.can_promote()`,
which requires *both* an independent authority decision *and* an
evidence threshold to be met -- neither substitutes for the other, and
neither is inferred from "the last operation succeeded."

## The execution pipeline

```
INTENT
  -> CAPABILITY CHECK      (governance.pipeline, capability_available flag)
  -> AUTHORITY CHECK       (governance.authority.evaluate_authority)
  -> RISK / APPROVAL CHECK (governance.approval, only if REQUIRES_APPROVAL)
  -> EXECUTE                (caller-supplied action_fn)
  -> VERIFY                 (caller-supplied verify_fn, optional)
  -> EVIDENCE RECORD        (governance.evidence)
  -> PROMOTION CHECK         (governance.promotion.can_promote, only if requested)
  -> STATE TRANSITION        (governance.evidence.institutionalize)
```

Implemented end-to-end in `governance/pipeline.py::run_pipeline()`. Every
stage either halts cleanly with a specific, explainable status (see the
`PipelineResult.status` values: `CAPABILITY_MISSING`, `AUTHORITY_DENIED`,
`AUTHORITY_UNKNOWN`, `HUMAN_ONLY_DENIED`, `AWAITING_APPROVAL`,
`EXECUTION_FAILED`, `EXECUTED_SUCCESS`, `PROMOTION_DENIED`, `PROMOTED`) or
proceeds -- no stage infers a downstream answer from an upstream pass.
Concretely: `capability_available=True` never causes an authority check
to be skipped; `decision.decision in AUTONOMOUS_EXECUTABLE_STATES` never
causes evidence recording to be skipped; a successful `EXECUTE` never
causes `PROMOTION CHECK` to be skipped when a promotion was requested.

## Authority states

Defined in `governance/types.py::AuthorityState`:

| State | Meaning |
|---|---|
| `DENIED` | Explicitly prohibited. |
| `ALLOWED` | May proceed, unrestricted within scope. |
| `ALLOWED_LOCAL` | May occur locally; may not cross an external trust boundary. |
| `ALLOWED_BOUNDED` | May execute only inside declared, checked constraints. |
| `REQUIRES_APPROVAL` | Execution requires a human `APPROVED` decision first. |
| `HUMAN_ONLY` | No autonomous agent may perform this, ever. |
| `UNAVAILABLE` | The authority mechanism itself cannot currently be reached. |
| `UNKNOWN` | Authority has not been established. **Never treated as ALLOWED.** |

`UNKNOWN` failing safe is enforced in three independent places, not just
documented:
1. `evaluate_authority()` returns `UNKNOWN` (never `ALLOWED`) for any
   capability with no matching policy, or a policy whose scope doesn't
   match the request, or an expired policy with no successor.
2. A bounded constraint the caller's `context` cannot verify makes the
   decision `UNKNOWN`, not a permissive pass-through.
3. `pipeline.run_pipeline()` treats `UNKNOWN` as a hard stop
   (`status="AUTHORITY_UNKNOWN"`) before `action_fn` is ever called --
   see `tests/governance/test_pipeline.py::test_unknown_authority_halts_and_never_executes`.

## Seed policy table

`governance/policy_defaults.json` -- fixtures/defaults, not a claim that
ForgeWorld already had these rules. Every decision is deliberately
conservative; none grants an agent broader authority than the NRM
incident already demonstrated the runtime actually has.

| Capability | Decision | Why |
|---|---|---|
| `WRITE_BRANCH` | `ALLOWED_BOUNDED` (no force-push) | Observed: succeeded in the incident. |
| `CREATE_TAG` | `ALLOWED_LOCAL` | Never touches the remote. |
| `PUSH_TAG` | `REQUIRES_APPROVAL` | Observed: HTTP 403 on the same credentials that just wrote a branch. |
| `DEPLOY` | `REQUIRES_APPROVAL` | Fixture default; no deployment integration exists yet. |
| `PROMOTE_RELEASE` | `HUMAN_ONLY` | Mission's explicit release-discipline requirement. |
| `SEND_EXTERNAL_MESSAGE` | `ALLOWED_BOUNDED` (empty channel allow-list) | Fixture default; nothing pre-approved. |
| `SPEND_FUNDS` | `ALLOWED_BOUNDED` (`max_amount: 0`) | Fixture default; no autonomous spend until a human sets a real threshold. |
| `DELETE_RECORD` | `REQUIRES_APPROVAL` | No undo primitive exists in this runtime. |
| `MODIFY_GOVERNANCE` | `HUMAN_ONLY` | Self-protection (see below). |
| `AUTHORIZE_AGENT` | `HUMAN_ONLY` | Agent creation is not authority creation (see below). |
| `CHANGE_PRODUCTION_CONFIGURATION` | `HUMAN_ONLY` | Same blast-radius tier as `PROMOTE_RELEASE`. |

## External trust boundaries

`governance/types.py::TrustBoundary` models the chain
`LOCAL_FILE -> GIT_COMMIT -> REMOTE_BRANCH -> REMOTE_TAG ->
DEPLOYMENT_PLATFORM -> PRODUCTION` (plus `EXTERNAL_COMMUNICATION`,
`FINANCIAL`, `GOVERNANCE` for the non-git examples). This is not a
permission ladder -- clearing boundary N never implies boundary N+1.
Mechanically, this is true because `evaluate_authority()` looks up a
policy strictly by `capability` name; there is no code path that reuses
one capability's decision for another. The NRM incident is the worked
example: `WRITE_BRANCH` clearing `REMOTE_BRANCH` did not, and structurally
cannot, grant anything about `PUSH_TAG` clearing `REMOTE_TAG` -- see
`tests/governance/test_authority.py::test_local_only_authority_cannot_cross_external_boundary`.

The same principle generalizes past git, per the mission brief: draft
email -> send email, draft ad -> spend money, prepare refund -> issue
refund, build release -> deploy release, generate contract -> execute
contract, create agent -> authorize agent. Each arrow is a boundary
crossing; each needs its own policy entry, not an inherited one.

## Delegation and self-escalation

`governance/delegation.py` enforces:

```
DELEGATED_AUTHORITY ⊆ DELEGATOR_AUTHORITY
```

`delegate_authority()` compares a requested decision's permissiveness
rank against the delegator's own *actual, evaluated* `AuthorityDecision`
(never a claim) and, for `ALLOWED_BOUNDED`, checks that every requested
constraint is itself a subset of the delegator's own constraint (e.g. a
delegated spend cap cannot exceed the delegator's own cap). `MODIFY_GOVERNANCE`
and `AUTHORIZE_AGENT` are additionally hard-blocked from delegation
regardless of the delegator's rank -- defense in depth, so a bug in
policy data alone can't enable self-escalation.

`guard_self_escalation()` is the entry point any governance-modifying or
agent-authorizing code path must call first. It denies every non-human
actor outright and logs an `AUTHORITY_ESCALATION_ATTEMPTED` audit event
regardless of outcome -- including on a *permitted* human change, so
there is always a trail.

This directly prevents the scenario the mission names: *agent A lacks
deploy authority; agent A creates agent B; B deploys anyway.* Creating an
agent identity is not, by itself, an authority grant -- every capability
agent B ever exercises goes through the same `evaluate_authority()` call
any other actor would, using the same policy table. There is no code
path in this repository where instantiating a new actor id changes what
`evaluate_authority()` returns for it.

## Approval lifecycle

`governance/approval.py`. States: `PENDING -> APPROVED | DENIED`, with
`PENDING` also lazily reading as `EXPIRED` past its `expires_at`, and
`APPROVED -> EXECUTED` exactly once (`mark_executed()` refuses a second
call for the same `approval_id` -- approval to perform one action does
not implicitly authorize a repeat). Only a `decider_kind="human"` caller
may call `decide_approval()`; an agent attempting it raises
`PermissionError` and leaves the request untouched.

## Failure taxonomy and retry policy

`execution/failure_classification.py`. The concrete reason this exists:
a bare HTTP 403 must not be filed as a generic network failure. HTTP
status codes carry real meaning -- 401 is an authentication problem, 403
is "authenticated, but not authorized for this" -- and `classify_failure()`
honors that distinction. Full detail:
[`docs/governance/AUTHORITY_FAILURE_TAXONOMY.md`](AUTHORITY_FAILURE_TAXONOMY.md).

## Audit trail

`governance/audit.py::emit()` is the single write path for every
authority-sensitive event (`AUTHORITY_CHECKED`, `AUTHORITY_GRANTED`,
`AUTHORITY_DENIED`, `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`,
`APPROVAL_DENIED`, `EXECUTION_STARTED`, `EXECUTION_SUCCEEDED`,
`EXECUTION_FAILED`, `EVIDENCE_RECORDED`, `PROMOTION_REQUESTED`,
`PROMOTION_GRANTED`, `PROMOTION_DENIED`, `AUTHORITY_ESCALATION_ATTEMPTED`),
appended to `governance/audit_log.jsonl` following the exact
append-only-jsonl convention already established by
`capabilities/history.jsonl` and `router/decisions.jsonl` -- no new
logging system was introduced.

## What this mission deliberately did not do

- Did not modify `router/mission_router.py`, which still routes purely on
  reachability + fit + cost. That router exhibiting the capability-as-authority
  pattern is now a documented, known gap (see "The incident that forced
  the distinction" above) -- wiring `evaluate_authority()` into it is a
  natural next step, but doing so was out of scope for this mission
  ("do not redesign unrelated architecture").
- Did not grant any agent broader authority than it already effectively
  had, anywhere in the seed policy table.
- Did not touch `capabilities/registry.json` or `capabilities/discover.py`
  -- capability and authority remain genuinely separate modules with no
  shared mutable state.
- Did not promote this architecture to constitutional/core status. That
  remains a human decision -- see the mission's final report (delivered
  as the completion message for FORGEWORLD-AUTHORITY-SEPARATION-001) for
  the promotion recommendation.
