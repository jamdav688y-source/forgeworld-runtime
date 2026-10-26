"""SYNTHETIC fixtures for CXP R1: two deterministic, rule-based consumers
and one source-bearing observation event. No model, network, account or
private data is involved. These exist to prove the exchange contract, not
to perform cognition -- the seven lenses are a later slice (R3)."""
from __future__ import annotations

import re

from cognition import cxp

# The Phase 0 commit's subject line, quoted verbatim from git history.
PHASE0_COMMIT = "jamdav688y-source/forgeworld-runtime@15a56f7d3c7299f937f3c5397f0bf80acb57cf9c"
PHASE0_SUBJECT = "Authorize governed fabric execution from receiver-held grants"
PHASE0_TESTS = "jamdav688y-source/forgeworld-runtime@15a56f7d3c7299f937f3c5397f0bf80acb57cf9c:fabric/tests/test_receiver_authorization.py"


def phase0_observation_event(observed_at: str = "2026-10-17T00:00:00Z", emitter_id: str = "synthetic-emitter-1") -> dict:
    return {
        "schema_version": cxp.SCHEMA_VERSION,
        "kind": cxp.KIND_OBSERVATION,
        "representation": cxp.REP_QUOTATION,
        "evidence": cxp.EV_SINGLE_SOURCE,
        "verification": cxp.VER_UNVERIFIED,
        "provenance": cxp.OBSERVED,
        "privacy": cxp.PRIV_INTERNAL,
        "payload": {"statement": PHASE0_SUBJECT, "subject": "phase-0-receiver-held-authorization"},
        "sources": [{"source_type": "git_commit", "locator": PHASE0_COMMIT}],
        "derived_from": [],
        "verification_ref": None,
        "consent_ref": None,
        "occurrence": {"emitter_id": emitter_id, "observed_at": observed_at,
                       "correlation_id": "cycle-r1-demo", "causation_id": None},
    }


class SourceAuditConsumer:
    """Reports the epistemic labels and source types of what it receives."""

    consumer_id = "synthetic-source-audit"

    def consume(self, record: cxp.CognitiveRecord) -> dict:
        return {
            "kind": record.kind,
            "representation": record.representation,
            "evidence": record.evidence,
            "verification": record.verification,
            "source_types": sorted({s.source_type for s in record.sources}),
            "parent_count": len(record.derived_from),
        }


_GOVERNANCE_TERMS = ("authorize", "governed", "grant", "grants", "permission", "receiver-held", "revoke")


class GovernanceTermConsumer:
    """Counts words and picks out governance vocabulary in the statement."""

    consumer_id = "synthetic-governance-terms"

    def consume(self, record: cxp.CognitiveRecord) -> dict:
        statement = record.payload().get("statement", "")
        words = re.findall(r"[a-z][a-z-]*", statement.lower())
        return {"word_count": len(words), "terms": sorted(set(words) & set(_GOVERNANCE_TERMS))}
