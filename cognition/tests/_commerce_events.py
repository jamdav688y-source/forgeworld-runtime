"""Test-only SYNTHETIC commercial fixtures. Every buyer, engagement,
document and payment here is invented; digests are hashes of fixture
labels, never of real references."""
import hashlib

from cognition import commerce, cxp
from cognition.tests import _events as ev

OFFER = "offer-workflow-loss-diagnostic"
PILOT_PRICE = {"minor": 500000, "currency": "USD"}  # the $5,000 price HYPOTHESIS, in cents


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def signal(stage, engagement="eng-pilot-a", account="acct-buyer-a", entry=None, independence_key=None,
           provenance=cxp.HUMAN_ASSERTED, representation=cxp.REP_PARAPHRASE, evidence=cxp.EV_SINGLE_SOURCE,
           verification=cxp.VER_UNVERIFIED, verification_ref=None, consent_ref="auto", privacy=cxp.PRIV_INTERNAL,
           observed_at="2026-10-17T02:00:00Z", **fields):
    payload = {"stage": stage, "engagement_ref": engagement, "account_ref": account}
    payload.update({k: None for k in commerce._ALL_FIELDS})
    payload.update(fields)
    if consent_ref == "auto":
        consent_ref = f"consent-{engagement}" if commerce.STAGE_RULES[stage].get("consent") else None
    source = ev.source(f"operator-log:{engagement}:{entry or stage.lower()}", source_type="human_statement",
                       independence_key=independence_key)
    return {
        "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_COMMERCIAL_SIGNAL,
        "representation": representation, "evidence": evidence, "verification": verification,
        "provenance": provenance, "privacy": privacy, "payload": payload, "sources": [source],
        "derived_from": [], "verification_ref": verification_ref, "consent_ref": consent_ref,
        "occurrence": {"emitter_id": "synthetic-operator", "observed_at": observed_at},
    }


def payment_check(content_id, method="payment-reconciliation", provenance=cxp.HUMAN_ASSERTED, outcome=cxp.VER_VERIFIED):
    event = ev.verification_result(content_id, outcome=outcome, provenance=provenance)
    event["payload"]["method"] = method
    event["sources"] = [ev.source("operator-log:payment-reconciliation", source_type="human_statement")]
    return event
