# ForgeWorld Sentinel Map

See `gap-matrix.md` #10. Corresponds to Section 9 of the mission brief.

## Classification: MISSING

No adversarial-risk-analysis layer exists anywhere in this repository.
There is no shared disposition vocabulary (ALLOW/CHALLENGE/HOLD/ESCALATE/
DENY/REQUIRE_HUMAN_REVIEW) anywhere in the code — this is a genuinely new
concept relative to everything built so far, not a rename or an extension
of something that already exists.

## What exists instead: domain-narrow adversarial defenses, not a Sentinel

These are real, tested, and worth reusing as *inputs* to a future Sentinel
rather than replacing:

| Defense | File | Threats covered | Tested |
|---|---|---|---|
| Archive safety | `artifact_handoff/zip_unpack.py` | path traversal, absolute paths, symlink entries, expansion bombs (per-member and aggregate), malformed archives, unsupported formats | 21/21 (part of `artifact_handoff` suite) |
| Wire framing safety | `fabric/loopback/wire.py` | malformed JSON, truncated messages, oversized messages (`max_bytes`), non-UTF-8 payloads | 17/17 + 12/12 |
| Transport hardening | `fabric/tcp/pc_node_server.py` | one-shot listener (refuses second connection), explicit capability allowlist (defense in depth beyond registry absence), bounded runtime/idle timeout | 12/12 |
| Identity/hash checks | `fabric/interface.py::validate_envelope()` | in-transit corruption (independent re-verification on the receiving side, not just the sender's own check) | proven across all three fabric suites |

None of these share a data model, a disposition vocabulary, or a policy-
evolution path. Each is a hand-written `if`/`try` chain specific to its own
domain.

## What Section 9 asks for that has zero precedent in this codebase

- Identity anomalies, counterparty inconsistencies, replay/duplicate
  behavior *across sessions* (as opposed to the narrow, single-connection
  duplicate-artifact check `FabricArtifactIndex` already does), unexpected
  scope expansion, capability misuse, device anomalies, provenance
  anomalies as a *continuous* analysis layer rather than a one-shot
  request-time check.
- The observation → candidate_pattern → evidence → adversarial_test →
  governance/human_review → policy_promotion pipeline Section 9 specifies
  for how Sentinel policy itself should evolve. Nothing like this exists;
  every defense listed above is a fixed, hand-coded check, not a policy
  that could be observed, proposed, tested, and promoted.
- Any composition point for an external system (the mission's own example:
  Stripe Radar for payment-network fraud). No payment, commercial, or
  external-network-risk integration exists anywhere in this repository
  (see `gap-matrix.md` #19 — Relationship/CommercialState is itself
  missing, so there is nothing yet for a Sentinel to protect in that
  domain specifically).

## Direct relevance to the disclosed authority-expiry gap

The unenforced `AuthorityContext.expires_at` (see `authority-map.md`) is
exactly the shape of thing a ForgeSentinel would eventually catch even if
the underlying `authority_permits()` function were never fixed directly —
an anomalous, still-being-honored "expired" grant is precisely an
"authority mismatch" per Section 9's domain list. Today, nothing would
notice.
