# ForgeWorld Authority Map

See `gap-matrix.md` #11, #12, and its "Governance risks" section.
Corresponds to Section 1's non-negotiable invariant and Section 6.

## The one real, tested authority gate in this codebase

`fabric/interface.py::AuthorityContext` + `authority_permits()`:

```python
def authority_permits(context: AuthorityContext, capability_id: str) -> bool:
    return capability_id in context.granted_capability_ids
```

`AuthorityContext` fields: `actor_id`, `granted_capability_ids` (tuple,
no wildcard value exists anywhere in the type or the check function),
`granted_by`, `granted_at`, `expires_at` (`Optional[str]`, structural
placeholder). Exercised by 48 passing tests across the fabric suites,
including an explicit test that a broad-but-still-explicit grant does
**not** authorize an arbitrary capability
(`test_phone_never_has_unrestricted_authority_by_default`). This is a real,
working, minimal implementation of "authority is a scoped grant, not
ambient" — the strongest existing piece of the target GovernanceEngine.

**Confirmed live gap:** `expires_at` is read nowhere. `authority_permits()`
does not import `time`, does not compare against `granted_at`/`expires_at`,
and no test constructs an expired context and expects rejection — because
today, nothing would reject it. This is a direct, disclosed exposure
against the mission's own stated invariant: *"Historical authorization
MUST NOT silently become current authority."* Fixing this is small,
bounded, and testable (see the recommended microphase in the final
report).

## The mission-evidence governance pattern (separate mechanism, same repository)

`evidence_envelope/envelope.py`: `BRONZE_RECEIVED → SILVER_STRUCTURED →
GOLD_VALIDATED`, with `REJECTED`/`QUARANTINED` as explicit failure states.
`record_promotion_authority()` records a verified attestation that a named
principal has promotion scope for an exact mission, but — by explicit
design, stated in its own docstring — does **not** itself flip
`promotion_status`. This is the same "recording authority is not the same
as exercising it" discipline as `fabric`'s `AuthorityContext`, arrived at
independently in a different subsystem. The two have never been unified;
doing so is a real recombination candidate for Section 11's
GovernanceEngine, not yet attempted.

`AuthorityVerificationRequest`/`VerifiedAuthority` (same file) define the
*shape* of an external authority check (principal_id, requested_scope,
statement in; principal_id, authority_scope, attestation_reference out —
deliberately no field for a credential/secret) but no concrete verifier
implementation exists in this repository. Native tests for this file are
`PRESENT_UNVERIFIED` in this sandbox (no pytest); the primitives it shares
with `lineage_store` (`_FileLock`, `_atomic_write_bytes`,
`validate_mission_id`) are proven transitively, but the authority-specific
dataclasses themselves are not exercised by anything this session could
run.

## What "network reachability != authorization" looks like in code today

Proven directly: `fabric/tcp/tests/test_fabric_tcp.py::TestUnauthorizedOverTCP`
constructs a fully successful, authenticated (`multiprocessing.connection`
authkey-challenge-passed) TCP connection, then sends a `RemoteCapabilityRequest`
with an empty `granted_capability_ids` — and gets `CAP_UNAUTHORIZED` back,
not `CAP_COMPLETED`. This is a real, passing test of exactly the invariant
Section 1/15 of this mission names. The equivalent test exists at the
loopback layer (`fabric/tests/test_fabric_loopback.py::TestUnauthorizedOverWire`)
and the pure-contract layer (`fabric/tests/test_fabric_contract.py::TestUnauthorizedRequest`)
— the same invariant proven at three transport layers independently.

## What is missing

A policy engine (GovernanceEngine, Section 11's target) that evaluates
more than "is this exact string in this exact tuple" — no time-based
expiry, no context-conditional grants (actor × action × context × time ×
policy, as Section 1 specifies, is currently only actor × action). No
human-approval interface backs any of this (see `sentinel-map.md` and
gap-matrix #20) — `granted_by` is a free-text string today
(`"operator_default_policy"` in every test), never validated against a
real principal.
