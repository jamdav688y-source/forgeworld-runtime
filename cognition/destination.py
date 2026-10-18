"""FW-ODCC-1: DESTINATION -- the integrity of outcomes.

An OUTCOME_SPEC is an immutable, human-authored CXP record that fixes what
"done" means BEFORE the work is accepted: intended outcome, acceptance
criteria (R2a's deterministic vocabulary) and their sha256, required
deliverables with media types, required disclosures, and the estimate
records that motivate the work. It derives from exactly the initiating
OBSERVATION / AUDIENCE_QUESTION records of one admitted, completed cycle
(cognition.origin) plus those estimates -- never from a claim, lens output
or any other inference.

A DeliveryPackage bound to a spec (delivery.assemble(outcome_spec_id=...))
must cite the spec in its lineage and carry the same project, customer,
synthetic flag and criteria hash; the exchange refuses anything else, and
refuses a real-customer package with no spec at all. A failed criterion is
never rewritten: revision_candidate() names it and keeps the hash.

OutcomeDesk.report() derives each stage from existing records only and
never collapses them:
    TECHNICAL_COMPLETION   machine checks passed on the intact anchored bundle
    HANDOFF_APPROVED       approving review + signed handoff (R2a events)
    DELIVERED              R2a DELIVERED event (operator-asserted)
    CUSTOMER_ACCEPTED      CUSTOMER_ACCEPTED event backed by customer evidence
    PAYMENT_CONFIRMED      commerce revenue VERIFIED_NET_RETAINED, only for an
                           engagement the caller names (no stored link exists)
    VALUE_MEASURED         an active VALUE_MEASURED commercial record
    REPEATABILITY_CANDIDATE  commerce.repeatability() for the spec's offer
    CAPABILITY_PROMOTED    always False: the promotion gate is not on this branch

Nothing here writes a record except propose(); revision and promotion
candidates are returned, never stored, and nothing starts a cycle, authorizes
work, contacts anyone or moves money.
"""
from __future__ import annotations

import json
import re

from cognition import commerce, cxp, delivery as dv, episode as ep, origin

SPEC_SCHEMA = "forgeworld.destination.outcome_spec.v1"
TECHNICAL_COMPLETION = "TECHNICAL_COMPLETION"
HANDOFF_APPROVED = "HANDOFF_APPROVED"
DELIVERED = "DELIVERED"
CUSTOMER_ACCEPTED = "CUSTOMER_ACCEPTED"
PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
VALUE_MEASURED = "VALUE_MEASURED"
REPEATABILITY_CANDIDATE = "REPEATABILITY_CANDIDATE"
CAPABILITY_PROMOTED = "CAPABILITY_PROMOTED"
STAGES = (TECHNICAL_COMPLETION, HANDOFF_APPROVED, DELIVERED, CUSTOMER_ACCEPTED, PAYMENT_CONFIRMED, VALUE_MEASURED,
          REPEATABILITY_CANDIDATE, CAPABILITY_PROMOTED)
PROMOTION_UNAVAILABLE = ("UNAVAILABLE: CapabilityPromotionGate exists only on unmerged Phase 1B (decision D1); "
                         "promotion is not simulated")

MAX_DELIVERABLES = 32
_KEYS = frozenset({"spec_id", "origin_cycle_id", "origin_cycle_artifact_id", "project_ref", "customer_ref",
                   "synthetic", "intended_outcome", "acceptance_criteria", "criteria_sha256",
                   "required_deliverables", "disclosures", "initiating_record_ids", "value_hypothesis_ids",
                   "author_id"})
_CYCLE_ID = re.compile(r"^cxp-cycle-[0-9a-f]{64}$")
_ARTIFACT_ID = re.compile(r"^cxp-art-[0-9a-f]{64}$")
_RECORD_ID = re.compile(r"^cxp-rec-[0-9a-f]{64}$")
_SPEC_ID = re.compile(r"^cxp-osp-[0-9a-f]{64}$")


class DestinationRefused(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


def _ids(value, allow_empty: bool) -> bool:
    return (isinstance(value, list) and (allow_empty or value) and value == sorted(set(value))
            and all(isinstance(v, str) and _RECORD_ID.match(v) for v in value))


def spec_id_of(payload: dict) -> str:
    return cxp.digest_id("outcome_spec", {k: v for k, v in payload.items() if k != "spec_id"})


# ---------------------------------------------------------------------------
# OUTCOME_SPEC record rules (called by cxp / exchange)
# ---------------------------------------------------------------------------

def check_spec_payload(payload: dict) -> None:
    def bad(detail):
        raise cxp.CXPError(cxp.E_MALFORMED, detail)
    if set(payload) != _KEYS:
        bad(f"OUTCOME_SPEC payload requires exactly {sorted(_KEYS)}")
    problems = dv.ref_problems(payload["project_ref"], payload["customer_ref"], payload["synthetic"])
    if problems:
        bad(problems[0])
    if not isinstance(payload["origin_cycle_id"], str) or not _CYCLE_ID.match(payload["origin_cycle_id"]):
        bad("origin_cycle_id is malformed")
    if not isinstance(payload["origin_cycle_artifact_id"], str) or not _ARTIFACT_ID.match(payload["origin_cycle_artifact_id"]):
        bad("origin_cycle_artifact_id is malformed")
    if not isinstance(payload["author_id"], str) or not ep._REVIEWER.match(payload["author_id"]):
        bad("author_id must be a human operator id (operator-<slug>)")
    dv._text(payload["intended_outcome"], "intended_outcome")
    criteria = payload["acceptance_criteria"]
    problems = dv.criteria_problems(criteria)
    if problems:
        bad(problems[0])
    if payload["criteria_sha256"] != dv.criteria_sha256(criteria):
        bad("criteria_sha256 does not match the acceptance criteria")
    deliverables = payload["required_deliverables"]
    if not isinstance(deliverables, list) or not 0 < len(deliverables) <= MAX_DELIVERABLES:
        bad(f"required_deliverables needs 1..{MAX_DELIVERABLES} entries")
    names = []
    for d in deliverables:
        if (not isinstance(d, dict) or set(d) != {"name", "media_type"} or not isinstance(d["name"], str)
                or not dv._ARTIFACT_NAME.match(d["name"]) or d["media_type"] != dv.media_type(d["name"])):
            bad("each required deliverable is {name, media_type} with the media type its name implies")
        names.append(d["name"])
    if names != sorted(set(names)):
        bad("required deliverables must be sorted by name and unique")
    for c in criteria:
        if "path" in c and c["path"] not in names:
            bad(f"criterion {c['criterion_id']} checks a file that is not a required deliverable")
    disclosures = payload["disclosures"]
    if not isinstance(disclosures, list):
        bad("disclosures must be a list")
    for text in disclosures:
        dv._text(text, "disclosure")
    if payload["synthetic"] and not any("synthetic" in t.lower() for t in disclosures):
        bad("a synthetic spec must disclose that it is synthetic")
    if not _ids(payload["initiating_record_ids"], allow_empty=False):
        bad("initiating_record_ids must be a sorted, non-empty list of record ids")
    if not _ids(payload["value_hypothesis_ids"], allow_empty=True):
        bad("value_hypothesis_ids must be a sorted list of record ids")
    if not isinstance(payload["spec_id"], str) or not _SPEC_ID.match(payload["spec_id"]) \
            or payload["spec_id"] != spec_id_of(payload):
        bad("spec_id must be the content address of the rest of the spec")


def check_spec_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if (provenance, representation, evidence, verification) != dv._HUMAN_LABELS:
        raise cxp.CXPError(cxp.E_KIND_RULE, "an OUTCOME_SPEC is a human commitment: HUMAN_ASSERTED, PARAPHRASE, NONE, "
                                            "UNVERIFIED -- declaring success criteria proves nothing")
    if list(derived_from) != sorted(set(payload["initiating_record_ids"]) | set(payload["value_hypothesis_ids"])):
        raise cxp.CXPError(cxp.E_KIND_RULE, "an OUTCOME_SPEC derives from exactly its initiating records and its "
                                            "value hypotheses")


def check_spec_transition(payload: dict, lookup) -> None:
    for rid in payload["initiating_record_ids"]:
        meta = lookup(rid)
        if meta is None or meta["erased"] or meta["kind"] not in origin.INITIATING_KINDS:
            raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "an initiating record must be an OBSERVATION or "
                                                         "AUDIENCE_QUESTION -- an inference cannot start an outcome")
    for rid in payload["value_hypothesis_ids"]:
        meta = lookup(rid)
        if (meta is None or meta["erased"] or meta["kind"] != cxp.KIND_COMMERCIAL_SIGNAL
                or meta["commerce"]["stage"] != commerce.ESTIMATE_RECORDED):
            raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "a value hypothesis must be an ESTIMATE_RECORDED signal")


def spec_metadata(payload: dict) -> dict:
    return {**{k: payload[k] for k in ("spec_id", "project_ref", "customer_ref", "synthetic", "criteria_sha256",
                                       "origin_cycle_id", "origin_cycle_artifact_id", "author_id")},
            "deliverables": [d["name"] for d in payload["required_deliverables"]]}


# ---------------------------------------------------------------------------
# the desk
# ---------------------------------------------------------------------------

class OutcomeDesk:
    def __init__(self, exchange, runner, delivery_desk: dv.DeliveryDesk):
        self.exchange = exchange
        self.runner = runner
        self.deliveries = delivery_desk

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def _spec_meta(self, spec_id: str):
        return next((m for m in self.exchange.all_record_metadata()
                     if not m["erased"] and (m.get("outcome_spec") or {}).get("spec_id") == spec_id), None)

    def spec(self, spec_id: str) -> dict:
        meta = self._spec_meta(spec_id)
        if meta is None:
            raise DestinationRefused(["UNKNOWN_OUTCOME_SPEC"])
        return {**self.exchange.get_record(meta["record_id"]).payload(), "record_id": meta["record_id"]}

    def propose(self, brief: dict, *, project_ref, customer_ref, synthetic, intended_outcome, acceptance_criteria,
                required_deliverables, disclosures, author_id, observed_at: str) -> dict:
        """Record the outcome contract. The ORIGIN brief is re-derived from the
        ledger and the cycle artifact; the caller's copy is only compared."""
        if self.runner.governor._active_cycles:
            raise DestinationRefused(["AUTHOR_DURING_RUNNING_CYCLE"])
        if not isinstance(author_id, str) or not ep._REVIEWER.match(author_id):
            raise DestinationRefused(["UNAUTHORIZED_AUTHOR: a human operator id (operator-<slug>) is required"])
        try:
            artifact = origin.admitted_cycle(self.runner, brief["cycle_artifact_id"])
        except origin.OriginRefused as exc:
            raise DestinationRefused(exc.reasons) from None
        initiating = origin.initiating_record_ids(self.exchange, artifact)
        if initiating != sorted(r["record_id"] for r in brief["initiating_records"]):
            raise DestinationRefused(["STALE_OR_ALTERED_ORIGIN_BRIEF"])
        hypotheses = sorted(h["record_id"] for h in brief["value_hypotheses"])
        payload = {"origin_cycle_id": artifact["governor_decision"]["cycle_id"],
                   "origin_cycle_artifact_id": brief["cycle_artifact_id"], "project_ref": project_ref,
                   "customer_ref": customer_ref, "synthetic": synthetic, "intended_outcome": intended_outcome,
                   "acceptance_criteria": acceptance_criteria,
                   "criteria_sha256": dv.criteria_sha256(acceptance_criteria) if isinstance(acceptance_criteria, list) else None,
                   "required_deliverables": sorted(({"name": n, "media_type": dv.media_type(n)}
                                                    for n in set(required_deliverables)), key=lambda d: d["name"]),
                   "disclosures": list(disclosures), "initiating_record_ids": initiating,
                   "value_hypothesis_ids": hypotheses, "author_id": author_id}
        try:
            payload["spec_id"] = spec_id_of(payload)
        except cxp.CXPError as exc:
            raise DestinationRefused([f"{exc.code}: {exc.detail}"]) from None
        receipt = self.deliveries._ingest(cxp.KIND_OUTCOME_SPEC, payload, sorted(set(initiating) | set(hypotheses)),
                                          author_id, observed_at)
        if receipt.status == "REJECTED":
            raise DestinationRefused([f"{receipt.error_code}: {receipt.detail}"])
        return {"spec_id": payload["spec_id"], "spec_record_id": receipt.record_id, "spec": payload}

    # -- read-only evaluation -------------------------------------------------------------

    def _body(self, package_id: str):
        try:
            return json.loads((self.deliveries.root / package_id / dv.DELIVERY_FILE).read_bytes())
        except (OSError, ValueError):
            return None

    def report(self, package_id: str, engagement_ref: str = None, payment_policy=None) -> dict:
        status = self.deliveries.status(package_id)
        meta = self.exchange.record_metadata(status["package_record_id"])["delivery_package"]
        events = {h["event"]: h["record_id"] for h in status["history"]}
        spec_id = meta.get("outcome_spec_id")
        spec, spec_problems = None, []
        if spec_id:
            spec = self.spec(spec_id)
            try:
                origin.admitted_cycle(self.runner, spec["origin_cycle_artifact_id"])
            except origin.OriginRefused as exc:
                spec_problems += exc.reasons
            if meta.get("criteria_sha256") != spec["criteria_sha256"]:
                spec_problems.append("CRITERIA_HASH_DIFFERS_FROM_SPEC")

        def stage(established, evidence, basis):
            return {"established": bool(established), "evidence": sorted(e for e in evidence if e), "basis": basis}

        outcome = status["customer_outcome"]
        stages = {
            TECHNICAL_COMPLETION: stage(meta["validation_passed"] and status["intact"], [status["package_record_id"]],
                                        "machine acceptance checks passed on the intact, anchored bundle"),
            HANDOFF_APPROVED: stage(status["signer_id"] is not None,
                                    [events.get(dv.REVIEW_APPROVED), events.get(dv.HANDOFF_SIGNED)],
                                    "approving review and signed handoff, by people other than the editor"),
            DELIVERED: stage(status["delivery"] is not None, [events.get(dv.EV_DELIVERED)],
                             "operator-asserted delivery of the anchored checksum list; receipt not confirmed"),
            CUSTOMER_ACCEPTED: stage(outcome is not None and outcome["event"] == dv.CUSTOMER_ACCEPTED,
                                     [events.get(dv.CUSTOMER_ACCEPTED), outcome and outcome["evidence_record_id"]],
                                     "customer-originated, version-specific quoted evidence"),
        }
        money = None
        if engagement_ref is not None:
            try:
                money = commerce.engagement_state(self.exchange, engagement_ref, payment_policy)
            except KeyError:
                money = None
        if money is None:
            reason = ("NO_ENGAGEMENT_NAMED: no record links this package to a payment" if engagement_ref is None
                      else "NO_COMMERCIAL_RECORDS_FOR_ENGAGEMENT")
            stages[PAYMENT_CONFIRMED] = stage(False, [], reason)
            stages[VALUE_MEASURED] = stage(False, [], reason)
        else:
            revenue = money["revenue"]
            stages[PAYMENT_CONFIRMED] = stage(
                revenue["status"] == commerce.REVENUE_VERIFIED, [],
                f"commerce revenue status {revenue['status']} for {engagement_ref} (link named by the caller, not "
                f"recorded); payment policy {money['policy_id']}")
            measured = money["milestones"].get(commerce.VALUE_MEASURED, [])
            stages[VALUE_MEASURED] = stage(bool(measured), list(measured), "active VALUE_MEASURED records")
        offers = sorted({h["offer_ref"] for h in self._hypotheses(spec) if h["offer_ref"]})
        repeat = [self.promotion_candidate(o, payment_policy) for o in offers]
        stages[REPEATABILITY_CANDIDATE] = stage(
            any(r["repeatability_status"] == commerce.REPEATABILITY_CANDIDATE for r in repeat), [],
            "commerce.repeatability() over the spec's offers: " + (", ".join(
                f"{r['offer_ref']}={r['repeatability_status']}" for r in repeat) or "no offer referenced"))
        stages[CAPABILITY_PROMOTED] = stage(False, [], PROMOTION_UNAVAILABLE)
        return {
            "package_id": package_id, "version": status["version"], "lifecycle_status": status["status"],
            "project_ref": status["project_ref"], "customer_ref": status["customer_ref"],
            "synthetic": status["synthetic"],
            "outcome_spec": ({"spec_id": spec_id, "record_id": spec["record_id"],
                              "criteria_sha256": spec["criteria_sha256"], "package_criteria_sha256": meta["criteria_sha256"],
                              "bound": not spec_problems, "problems": spec_problems}
                             if spec else {"spec_id": None, "bound": False,
                                           "problems": ["UNBOUND: synthetic/internal package without an outcome spec"]}),
            "stages": stages,
            "value_hypotheses": self._hypotheses(spec),
            "return_path": {"customer_evidence_record_ids": [outcome["evidence_record_id"]] if outcome else [],
                            "eligible_as": "a new ORIGIN input, only through CycleRunner and the R4 governor",
                            "started_automatically": False},
            "identities_authenticated": False, "grants_execution_authority": False,
        }

    def _hypotheses(self, spec) -> list:
        out = []
        for rid in (spec or {}).get("value_hypothesis_ids", ()):
            p = self.exchange.get_record(rid).payload()
            out.append({"record_id": rid, "reason": p["reason"], "amount": p["amount"], "offer_ref": p["offer_ref"],
                        "status": "HYPOTHESIS_NOT_REVENUE"})
        return out

    def revision_candidate(self, package_id: str) -> dict:
        """A bounded proposal for a human, never stored and never acted on."""
        status = self.deliveries.status(package_id)
        meta = self.exchange.record_metadata(status["package_record_id"])["delivery_package"]
        base = {"package_id": package_id, "version": status["version"], "automatic": False, "ledger_writes": 0}
        if status["superseded_by"]:
            return {**base, "candidate": None, "reason": "ALREADY_REVISED", "superseded_by": status["superseded_by"]}
        body = self._body(package_id) or {}
        events = {h["event"]: h["record_id"] for h in status["history"]}
        failed = [{"criterion_id": r["criterion_id"], "check": r["check"], "detail": r["detail"]}
                  for r in body.get("validation_results", ()) if r["result"] == dv.FAIL]
        triggers = []
        if failed:
            triggers.append({"trigger": "FAILED_CRITERIA", "evidence": [status["package_record_id"]]})
        if not status["intact"]:
            triggers.append({"trigger": "INTEGRITY_FAILURE", "evidence": status["integrity_problems"]})
        for event in (dv.REVIEW_NEEDS_REVISION, dv.REVIEW_REJECTED):
            if event in events:
                triggers.append({"trigger": event, "evidence": [events[event]]})
        outcome = status["customer_outcome"]
        if outcome and outcome["event"] in (dv.CUSTOMER_REVISION_REQUESTED, dv.CUSTOMER_REJECTED):
            triggers.append({"trigger": outcome["event"],
                             "evidence": [events[outcome["event"]], outcome["evidence_record_id"]]})
        if not triggers:
            return {**base, "candidate": None, "reason": "NO_REVISION_INDICATED"}
        return {**base, "candidate": {
            "next_version": status["version"] + 1, "predecessor_package_id": package_id,
            "failed_criteria": failed, "triggers": triggers,
            "must_keep": {"project_ref": status["project_ref"], "customer_ref": status["customer_ref"],
                          "synthetic": status["synthetic"], "outcome_spec_id": meta.get("outcome_spec_id"),
                          "criteria_sha256": meta.get("criteria_sha256")},
            "requires": ["an editor's new version (DeliveryDesk.assemble with predecessor_package_id)",
                         "a fresh review by someone other than the editor", "a fresh signed handoff"],
            "criteria_may_change": False}}

    def promotion_candidate(self, offer_ref: str, payment_policy=None) -> dict:
        r = commerce.repeatability(self.exchange, offer_ref, payment_policy)
        return {"offer_ref": offer_ref, "repeatability_status": r["status"],
                "independent_buyers": r["independent_buyers"],
                "minimum_independent_buyers": r["minimum_independent_buyers"],
                "qualifying_engagements": r["qualifying_engagements"],
                "capability_promoted": False, "promotion_gate": PROMOTION_UNAVAILABLE,
                "promotion_requires_human_decision": True, "grants_execution_authority": False}
