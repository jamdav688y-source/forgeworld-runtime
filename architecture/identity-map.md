# ForgeWorld Identity Map

What currently establishes "who/what is this" across the repository.
See `gap-matrix.md` #3 for classification.

## Node identity (real, tested)

`fabric/interface.py::NodeIdentity` — `node_id` (validated via
`evidence_envelope.validate_mission_id`'s canonical `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`
contract, reused rather than reimplemented), `node_type` ∈
`{PC_NODE, PHONE_NODE}`, `display_name`, `locality` (always `local_only`
today). Two concrete node identities are exercised in tests:
`PC-NODE-MAIN`/`PC-NODE-LOOPBACK`/`PC-NODE-LOOPBACK` (test fixtures) and
`PHONE-NODE-*` (test fixtures). No real, persistent, operator-assigned
node identity exists yet for the actual Windows PC or the actual Android
phone — every identity used so far is a test-time string.

## Artifact identity

`artifact_handoff/interface.py::new_artifact_id()` and
`fabric/interface.py::build_artifact_envelope()` both mint identities via
the same `validate_mission_id` contract (`ART-<uuid4hex>` /
`ENV-<uuid4hex>` conventions). `artifact_handoff.Manifest.artifact_id` is
freshly minted **per local ingestion event** — it is not a stable
cross-node identity. `fabric.ArtifactEnvelope.artifact_id` is the
cross-node-stable identity a phone assigns once. These two identity
spaces are related but distinct by design (see
`artifact_handoff/interface.py` docstring on `new_artifact_id()`); nothing
currently reconciles "the same real-world artifact ingested twice locally
under two different Manifest.artifact_ids."

## Mission identity

`evidence_envelope/envelope.py::validate_mission_id()` is the canonical
identifier contract every other identity space in this repository reuses
(`artifact_id`, `envelope_id`, `node_id`, `receipt_id`, request/transfer
IDs). This is the single most load-bearing piece of shared identity
infrastructure in the codebase — **PROVEN_WORKING** transitively through
every suite that constructs any of the above (146/146 tests, this session).

## Authority/actor identity

`fabric/interface.py::AuthorityContext.actor_id` — a bare string, no
schema, no verification that the string corresponds to a real registered
node/human. `evidence_envelope.py::AuthorityVerificationRequest`/
`VerifiedAuthority.principal_id` — same shape, also unverified against any
real principal registry (no registry of principals exists).

## What is missing

No identity primitive spans models/agents/sessions — "Claude Code session
X" and "a future GPT-based agent" have no shared identity representation
anywhere. No human/operator identity model exists. No cross-repository or
cross-device identity linking exists (the Windows checkout's divergent
branch/HEAD, discovered in the prior reconciliation mission, could not be
resolved to "is this the same lineage" precisely because no identity
primitive spans repositories).
