# AUTHORITY_FAILURE_TAXONOMY.md

Implementation: `execution/failure_classification.py`.

## Why this exists

The proximate trigger was a single line of output:

```
error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403
```

Treating that as "a network error, retry it" is wrong on the merits (403
is not a connectivity problem -- the TCP connection succeeded, the
request reached the server, and the server responded deliberately) and
wrong in practice (it was retried three times with backoff before this
mission and got HTTP 403 all three times, because retrying does not
change who is authorized to do what). This taxonomy exists so that
distinction is made once, in code, instead of re-litigated ad hoc by
whichever agent happens to hit it next.

## Categories

`governance/types.py::FailureCategory`:

| Category | Meaning | Example |
|---|---|---|
| `CAPABILITY_MISSING` | The tool/service itself isn't reachable. | `git` not on `PATH`. |
| `AUTHORITY_DENIED` | Authenticated, but not authorized for this specific operation. | **HTTP 403.** |
| `AUTHORITY_UNKNOWN` | No policy exists to evaluate against. | A brand-new capability nobody wrote a policy for yet. |
| `APPROVAL_REQUIRED` | Authority policy says `REQUIRES_APPROVAL`; no `APPROVED` request exists yet. | `PUSH_TAG` in this repository, by default policy. |
| `AUTHENTICATION_FAILED` | The credentials themselves are wrong/expired. | HTTP 401. |
| `NETWORK_TRANSIENT` | A real, retryable connectivity problem. | Connection timeout, HTTP 5xx. |
| `NETWORK_PERMANENT` | A connectivity problem no retry will fix without reconfiguration. | DNS resolution failure. |
| `RATE_LIMIT` | Too many requests, not a permission problem. | HTTP 429. |
| `TARGET_REJECTED` | The specific target was invalid/conflicting, not an auth problem. | HTTP 404/409/422. |
| `VALIDATION_FAILED` | The proposed action failed a correctness check before/during execution. | Malformed input. |
| `EVIDENCE_INSUFFICIENT` | Evidence doesn't meet the bar a promotion/decision requires. | Trying to promote on `OBSERVED` when `VALIDATED` is required. |
| `PROMOTION_DENIED` | The independent promotion gate said no. | `can_promote()` returned `allowed=False`. |
| `EXECUTION_ERROR` | Anything else -- a genuine, uncategorized failure. | Unexpected exception. |

## Classification logic (`classify_failure()`)

Explicit flags passed by an already-informed caller (e.g.
`governance.pipeline`, which knows it halted on `APPROVAL_REQUIRED`
without needing to guess) take precedence over text/status inference.
Absent those, HTTP status is interpreted by its actual semantics -- not
by "2xx good, everything else bad":

- **401 -> `AUTHENTICATION_FAILED`** (the identity claim itself failed)
- **403 -> `AUTHORITY_DENIED`** (identity accepted, operation refused --
  this is the NRM incident's exact code, and the reason this taxonomy
  exists)
- **429 -> `RATE_LIMIT`**
- **500/502/503/504 -> `NETWORK_TRANSIENT`**
- **400/404/409/410/422 -> `TARGET_REJECTED`**

When no clean status code is available (as with `git push`'s stderr-only
error reporting), `classify_failure()` extracts one via regex
(`\bHTTP\s+(\d{3})\b`) before falling through to text-keyword matching
for DNS/timeout-style failures. `classify_git_push_failure()` is a thin,
named wrapper for this exact shape of failure, used directly in the NRM
regression fixture (`tests/governance/test_nrm_incident.py`).

## Retryability

`RETRY_POLICIES` maps every category to a `RetryPolicy(retryable,
max_attempts, backoff, guidance)`:

| Category | Retryable | Max attempts | Rationale |
|---|---|---|---|
| `NETWORK_TRANSIENT` | Yes | 4 | Matches this repository's own documented 2s/4s/8s/16s exponential-backoff convention for git fetch/pull/push network errors. |
| `RATE_LIMIT` | Yes | 3 | Bounded, should respect a `Retry-After` hint where available. |
| `EXECUTION_ERROR` | Yes | 1 | One bounded retry for a plain unexpected error, then escalate. |
| `AUTHORITY_DENIED` | **No** | 0 | Retrying does not change who is authorized. Escalate instead. |
| `AUTHORITY_UNKNOWN` | No | 0 | Establish authority explicitly before trying again. |
| `APPROVAL_REQUIRED` | No | 0 | Pause and escalate; do not attempt again until `APPROVED`. |
| `AUTHENTICATION_FAILED` | No | 0 | Wrong/expired credentials; retrying the identical request is pointless. |
| `NETWORK_PERMANENT` | No | 0 | Needs configuration repair, not persistence. |
| `CAPABILITY_MISSING` | No | 0 | Needs provisioning, not persistence. |
| `TARGET_REJECTED` | No | 0 | Needs a different/repaired target. |
| `VALIDATION_FAILED` | No | 0 | Repair and revalidate; retrying the identical action changes nothing. |
| `EVIDENCE_INSUFFICIENT` | No | 0 | Gather stronger evidence; execution retries don't strengthen evidence. |
| `PROMOTION_DENIED` | No | 0 | Promotion needs its own authority/evidence, unrelated to re-executing. |

`HUMAN_ONLY` deliberately does not appear in this table: it is an
authority-check outcome handled entirely at that stage (the pipeline
halts before `EXECUTE` is ever reached for a non-human actor), not a
post-execution failure to classify or retry.
