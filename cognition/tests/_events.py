"""Test-only builders for synthetic CXP events."""
import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cognition import cxp, synthetic  # noqa: E402


def observation(statement="The receiver, not the requester, holds the grant.", sources=None, **overrides):
    event = synthetic.phase0_observation_event()
    event["payload"] = {"statement": statement}
    if sources is not None:
        event["sources"] = sources
    event.update(overrides)
    return event


def claim(parents, statement="ForgeWorld cannot give itself permission.", **overrides):
    event = {
        "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_CLAIM, "representation": cxp.REP_INFERENCE,
        "evidence": cxp.EV_SINGLE_SOURCE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.DERIVED,
        "privacy": cxp.PRIV_INTERNAL, "payload": {"statement": statement}, "sources": [],
        "derived_from": list(parents), "verification_ref": None, "consent_ref": None,
        "occurrence": {"emitter_id": "synthetic-emitter-1", "observed_at": "2026-10-17T00:01:00Z"},
    }
    event.update(overrides)
    return event


def verification_result(target_content_id, outcome=cxp.VER_VERIFIED, **overrides):
    event = {
        "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_VERIFICATION_RESULT,
        "representation": cxp.REP_PARAPHRASE, "evidence": cxp.EV_SINGLE_SOURCE,
        "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED, "privacy": cxp.PRIV_INTERNAL,
        "payload": {"target_content_id": target_content_id, "outcome": outcome, "method": "operator-review"},
        "sources": [{"source_type": "test_run", "locator": synthetic.PHASE0_TESTS}],
        "derived_from": [], "verification_ref": None, "consent_ref": None,
        "occurrence": {"emitter_id": "synthetic-operator", "observed_at": "2026-10-17T00:02:00Z"},
    }
    event.update(overrides)
    return event


def contradiction(claims, summary="These claims cannot both hold.", conditions=None, **overrides):
    claims = sorted(claims)
    event = {
        "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_CONTRADICTION, "representation": cxp.REP_INFERENCE,
        "evidence": cxp.EV_SINGLE_SOURCE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.DERIVED,
        "privacy": cxp.PRIV_INTERNAL,
        "payload": {"claims": claims, "summary": summary,
                    "resolution_conditions": conditions or ["an operator-reviewed test run decides between them"]},
        "sources": [], "derived_from": claims, "verification_ref": None, "consent_ref": None,
        "occurrence": {"emitter_id": "synthetic-emitter-1", "observed_at": "2026-10-17T00:03:00Z"},
    }
    event.update(overrides)
    return event


def source(locator, source_type="synthetic_fixture", independence_key=None):
    s = {"source_type": source_type, "locator": locator}
    if independence_key is not None:
        s["independence_key"] = independence_key
    return s


def with_occurrence(event, **occ):
    event = copy.deepcopy(event)
    event["occurrence"].update(occ)
    return event
