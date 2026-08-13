# NRM_TAG_403_CASE.md

**Evidence state:** VALIDATED (see below for why, per
`governance.types.EvidenceState`)
**Subject:** the single incident that motivated
FORGEWORLD-AUTHORITY-SEPARATION-001

## OBSERVED FACTS

Verbatim, from this session's actual command output, in order:

1. `git push -u origin claude/next-right-move-pwa-t0h6p5` (a branch push)
   succeeded:
   ```
   To https://github.com/jamdav688y-source/forgeworld-runtime
      449793b..fd219f5  claude/next-right-move-pwa-t0h6p5 -> claude/next-right-move-pwa-t0h6p5
   branch 'claude/next-right-move-pwa-t0h6p5' set up to track 'origin/claude/next-right-move-pwa-t0h6p5'.
   ```
2. `git push origin NRM-v0.1-CLASSROOM` (a tag push), run immediately
   after, with the same session credentials, against the same remote,
   returned:
   ```
   error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403
   send-pack: unexpected disconnect while reading sideband packet
   fatal: the remote end hung up unexpectedly
   ```
3. The tag push was retried twice more (2s and 4s later, bounded
   exponential backoff), and returned the identical HTTP 403 both times.
4. `git ls-remote --tags origin | grep NRM` returned nothing -- the tag
   was confirmed absent from the remote after the failed attempts.
5. The local annotated tag object remained intact throughout: `git
   rev-parse NRM-v0.1-CLASSROOM^{commit}` continued to resolve to the
   correct commit before, during, and after the failed push attempts.
6. A later attempt in a follow-up session, on a freshly re-verified tag
   (recreated at a newer commit, same tag name), also returned HTTP 403
   on push, while an unrelated new branch (`claude/next-right-move-abcd-mode`)
   pushed successfully with the same credentials in the same session.

## INFERENCES

Clearly labeled as inferences -- not re-stated as fact:

- **Inference A:** the runtime's GitHub credentials for this repository
  are scoped to permit writes to `refs/heads/*` but not to
  `refs/tags/*`, most likely via a branch-protection or ref-protection
  rule, an app/token permission boundary, or an organization policy on
  this specific repository (`jamdav688y-source/forgeworld-runtime`).
- **Inference B:** this is a stable property of this repository's
  current configuration, not a transient fluke -- it reproduced
  identically across two separate sessions and multiple attempts.
- **Inference C:** HTTP 403 (as opposed to 401) supports Inference A
  specifically: the credentials themselves were accepted (else it would
  plausibly have been 401), but the specific operation was refused.

## What this case does NOT support

This is one repository's tag-ref permission configuration, observed at
one point in time, via one credential set. It does **not** establish:

- that GitHub tag pushes are *generally* more restricted than branch
  pushes across all repositories, orgs, or token types -- many GitHub
  repositories permit both freely;
- the *exact* mechanism (branch protection vs. app permission scope vs.
  org policy) without inspecting the repository's actual settings, which
  this runtime does not have access to;
- that this will remain true indefinitely -- a permission change on
  GitHub's side would invalidate Inference A without invalidating the
  observed facts above.

`governance/policy_defaults.json`'s `PUSH_TAG` policy is written to
reflect exactly this scope: a conservative default (`REQUIRES_APPROVAL`)
justified by this specific repository's specific observed behavior, not
a claim about GitHub tag permissions in general. Anyone porting this
policy table to a different repository should re-verify rather than
assume.

## SYSTEM RESPONSE

**Before this mission:** none of the following existed. The failure was
handled entirely by a human-supervised agent reasoning about it in
conversation -- correctly, in that case (bounded retries, no fabricated
success, escalated to the user with an accurate explanation), but with
no reusable mechanism enforcing that same discipline next time.

**After this mission**, replayed through `governance.pipeline.run_pipeline()`
(see `tests/governance/test_nrm_incident.py::test_nrm_incident_full_regression`,
which is this case's permanent regression fixture):

1. `WRITE_BRANCH` is evaluated independently and returns `ALLOWED_BOUNDED`
   -- matches observed fact 1.
2. `PUSH_TAG` is evaluated independently and returns `REQUIRES_APPROVAL`
   -- the pipeline halts **before** attempting the push at all. No live
   403 is needed to know to stop; the policy already reflects the
   observed history.
3. An `ApprovalRequest` is created (`PENDING`), with a human-readable
   `reason` and `proposed_action`, and an `APPROVAL_REQUESTED` audit
   event is emitted.
4. The local tag (`CREATE_TAG`, `ALLOWED_LOCAL`) remains completely
   unaffected -- it is a different capability, evaluated independently.
5. If a live 403 is hit anyway (e.g. a future policy change makes
   `PUSH_TAG` `ALLOWED` and the remote still refuses it), the attempt
   is still recorded (`EXECUTION_STARTED`), the failure is classified as
   `AUTHORITY_DENIED` (not a network error), no `EXECUTION_SUCCEEDED`
   event is ever emitted, evidence is recorded at `OBSERVED` (not
   `VALIDATED`), and the retry policy for `AUTHORITY_DENIED` is zero
   further attempts.
6. `WRITE_BRANCH`'s own authority is unaffected by any of this --
   verified directly via a fresh `evaluate_authority()` call after the
   `PUSH_TAG` failure, still returning `ALLOWED_BOUNDED`.
7. Once a human actually calls `decide_approval(..., decider_kind="human")`
   with `APPROVED`, a re-run of the pipeline finds the approved request,
   executes exactly once, and consumes it (`mark_executed`) -- a further
   attempt requires a fresh approval.

## REUSABLE PRINCIPLE

The reusable takeaway is not "GitHub tag pushes are always restricted."
It is:

> **A capability that is reachable is not thereby authorized.** Two
> operations that share every technical precondition (same tool, same
> credentials, same remote, same moment) can have different authority
> postures, because authority is a property of the *specific operation*,
> not of the technical means used to attempt it. When one such operation
> fails and a sibling succeeds, classify the failure by what actually
> happened (here: HTTP 403, an authorization signal) rather than by
> which bucket is easiest to retry into, and encode the boundary you just
> discovered as a policy so the next attempt doesn't have to rediscover
> it by trial and error.

This generalizes past git identically to how the mission brief frames
it: draft email vs. send email, draft ad vs. spend money, prepare refund
vs. issue refund, build release vs. deploy release, generate contract vs.
execute contract, create agent vs. authorize agent. Each pair looks like
"the same capability, just further along" and is not -- each needs its
own authority evaluation.
