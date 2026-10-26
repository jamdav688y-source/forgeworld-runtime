"""FW-COMMERCE-C1-IMPLEMENTATION-001: commercial evidence records and the
derived engagement state.

Every commercial fact is a CXP COMMERCIAL_SIGNAL record: a ROOT record
(it cites the source a human or system recorded it from) with a strict,
stage-specific payload. Records are append-only. Nothing here ever edits or
deletes one; the CURRENT state of an engagement is recomputed from all of
them on every call, so the same records always give the same answer.

THE DISTINCTIONS THIS MODULE EXISTS TO KEEP
  buyer interest (INTEREST_CONFIRMED)   != purchase approval (CONTRACT_SIGNED)
  proposal (PROPOSAL_SENT)              != contract (CONTRACT_SIGNED)
  invoice (INVOICE_ISSUED)              != payment (PAYMENT_CONFIRMED, verified)
  verified gross payment                != net retained revenue (after refunds,
                                           lost disputes, and open disputes held)
  demonstration (DEMONSTRATION_GIVEN)   != customer acceptance (CUSTOMER_ACCEPTANCE)
  estimate (ESTIMATE_RECORDED, HYPOTHESIS) != measurement (VALUE_MEASURED)
  one paid, accepted, measured engagement != repeatable capability (needs
                                           independent buyers AND a human decision)

WHO MAY SAY WHAT
  Only OPPORTUNITY_IDENTIFIED and ESTIMATE_RECORDED may come from anything
  other than a human, and even those never from an interpretation: CXP
  provenance DERIVED or UNVERIFIED_INTERPRETATION (lens and model output)
  is refused for every stage. Buyer, contract, money, delivery, acceptance,
  correction and reversal stages require HUMAN_ASSERTED.
  A PAYMENT_CONFIRMED counts toward revenue only when some record for that
  payment reference is VERIFIED through a VERIFICATION_RESULT that a
  caller-supplied, human-approved PaymentPolicy admits (provenance and
  method). Without a policy nothing is counted as paid.

WHAT IS STORED ABOUT MONEY AND PEOPLE
  Amounts are {"minor": int, "currency": ISO-4217} -- floats are refused by
  CXP's canonicalizer. Payments, documents and invoices are referenced only
  by "sha256:<hex>" digests the operator computes; raw bank, card or
  processor identifiers have no field to go in. Buyers are opaque
  "acct-..." pseudonyms. The one free-text field (summary) refuses
  e-mail addresses, long digit runs (phone/card/account numbers) and banking
  keywords. PERSONAL/RESTRICTED records are refused by the exchange.

CORRECTION vs REVERSAL vs REFUND
  CORRECTION  the target was entered in error and never happened: it is
              VOIDED (a correction of a correction restores the original).
  REVERSAL    the target happened and was later undone (contract cancelled,
              acceptance withdrawn, invoice voided): it stops counting.
  REFUND / DISPUTE  money specifically: a refund or a lost dispute reduces
              net retained revenue for that payment reference; an open
              dispute holds its amount out until resolved.
  In all cases the original record stays in the ledger, and the state
  report lists what was voided, reversed or refunded and by which record.

This module grants no execution authority, issues no payments, and
contacts no one. repeatability() reports a CANDIDATE at most; promotion to
a repeatable commercial capability is a human decision recorded elsewhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cognition import cxp, lineage

# --- stages ------------------------------------------------------------------
OPPORTUNITY_IDENTIFIED = "OPPORTUNITY_IDENTIFIED"
ESTIMATE_RECORDED = "ESTIMATE_RECORDED"
PROBLEM_QUALIFIED = "PROBLEM_QUALIFIED"
INTEREST_CONFIRMED = "INTEREST_CONFIRMED"
DEMONSTRATION_GIVEN = "DEMONSTRATION_GIVEN"
PROPOSAL_SENT = "PROPOSAL_SENT"
CONTRACT_SIGNED = "CONTRACT_SIGNED"
INVOICE_ISSUED = "INVOICE_ISSUED"
PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
REFUND_ISSUED = "REFUND_ISSUED"
DISPUTE_OPENED = "DISPUTE_OPENED"
DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
DELIVERY_MILESTONE = "DELIVERY_MILESTONE"
CUSTOMER_ACCEPTANCE = "CUSTOMER_ACCEPTANCE"
VALUE_MEASURED = "VALUE_MEASURED"
RENEWAL = "RENEWAL"
REFERRAL = "REFERRAL"
CHURNED = "CHURNED"
LOST = "LOST"
CORRECTION = "CORRECTION"
REVERSAL = "REVERSAL"

_HUMAN = (cxp.HUMAN_ASSERTED,)
_RECORDED = (cxp.REP_QUOTATION, cxp.REP_PARAPHRASE)

# stage -> rules. required/forbidden name payload fields that must be non-null
# / null; every other optional field may be either. "after" lists stages of
# which at least one ACTIVE record must already exist in the engagement
# (all lists must be satisfied). "target" constrains target_record's stage.
_ALL_FIELDS = ("offer_ref", "amount", "document_digest", "payment_reference_digest", "target_record", "reason", "summary")
STAGE_RULES = {
    OPPORTUNITY_IDENTIFIED: dict(provenance=(cxp.OBSERVED, cxp.HUMAN_ASSERTED, cxp.SYSTEM_ASSERTED),
                                 representation=(cxp.REP_QUOTATION, cxp.REP_PARAPHRASE, cxp.REP_INFERENCE),
                                 required=("summary",), forbidden=("amount", "payment_reference_digest", "target_record")),
    ESTIMATE_RECORDED: dict(provenance=(cxp.HUMAN_ASSERTED, cxp.SYSTEM_ASSERTED), representation=(cxp.REP_HYPOTHESIS,),
                            required=("amount", "reason"), forbidden=("payment_reference_digest", "target_record"),
                            reasons=("ESTIMATED_SAVINGS", "ESTIMATED_REVENUE", "ESTIMATED_DELIVERY_COST",
                                     "PRICE_HYPOTHESIS"), never_verified=True),
    PROBLEM_QUALIFIED: dict(required=("summary",), forbidden=("amount", "payment_reference_digest", "target_record"),
                            consent=True),
    INTEREST_CONFIRMED: dict(required=("summary",), forbidden=("amount", "payment_reference_digest", "target_record"),
                             consent=True),
    DEMONSTRATION_GIVEN: dict(required=("summary",), forbidden=("amount", "payment_reference_digest", "target_record")),
    PROPOSAL_SENT: dict(required=("offer_ref", "amount", "document_digest"),
                        forbidden=("payment_reference_digest", "target_record")),
    CONTRACT_SIGNED: dict(required=("offer_ref", "amount", "document_digest"),
                          forbidden=("payment_reference_digest", "target_record"), after=((PROPOSAL_SENT,),)),
    INVOICE_ISSUED: dict(required=("amount", "document_digest"), forbidden=("payment_reference_digest", "target_record"),
                         after=((CONTRACT_SIGNED,),)),
    PAYMENT_CONFIRMED: dict(required=("amount", "payment_reference_digest"), forbidden=("target_record",),
                            after=((CONTRACT_SIGNED,),)),
    REFUND_ISSUED: dict(required=("amount", "payment_reference_digest"), forbidden=("target_record",), after_payment=True),
    DISPUTE_OPENED: dict(required=("amount", "payment_reference_digest"), forbidden=("target_record",), after_payment=True),
    DISPUTE_RESOLVED: dict(required=("target_record", "reason"), forbidden=("amount", "payment_reference_digest"),
                           target=(DISPUTE_OPENED,), reasons=("WON", "LOST")),
    DELIVERY_MILESTONE: dict(required=("summary",), forbidden=("amount", "payment_reference_digest", "target_record"),
                             after=((CONTRACT_SIGNED,),)),
    CUSTOMER_ACCEPTANCE: dict(required=("document_digest",), forbidden=("amount", "payment_reference_digest", "target_record"),
                              after=((CONTRACT_SIGNED,), (DELIVERY_MILESTONE,))),
    VALUE_MEASURED: dict(required=("amount", "document_digest", "reason"), forbidden=("payment_reference_digest", "target_record"),
                         reasons=("MEASURED_SAVINGS", "MEASURED_REVENUE_GAIN"), after=((CUSTOMER_ACCEPTANCE,),)),
    RENEWAL: dict(required=("amount", "document_digest"), forbidden=("payment_reference_digest", "target_record"),
                  after=((CUSTOMER_ACCEPTANCE,),)),
    REFERRAL: dict(required=("summary",), forbidden=("amount", "payment_reference_digest", "target_record"),
                   after=((CUSTOMER_ACCEPTANCE,),)),
    CHURNED: dict(required=("reason",), forbidden=("amount", "payment_reference_digest", "target_record"),
                  reasons=("NOT_RENEWED", "CANCELLED", "DISSATISFIED", "OTHER"), after=((CONTRACT_SIGNED,),)),
    LOST: dict(required=("reason",), forbidden=("amount", "payment_reference_digest", "target_record"),
               reasons=("PRICE", "RELEVANCE", "TIMING", "COMPETITOR", "NO_RESPONSE", "OTHER")),
    CORRECTION: dict(required=("target_record", "reason"), forbidden=("amount", "payment_reference_digest"),
                     target="ANY", reasons=("ENTERED_IN_ERROR", "WRONG_AMOUNT", "WRONG_ENGAGEMENT", "DUPLICATE_ENTRY")),
    REVERSAL: dict(required=("target_record", "reason"), forbidden=("amount", "payment_reference_digest"),
                   target=(INTEREST_CONFIRMED, PROPOSAL_SENT, CONTRACT_SIGNED, INVOICE_ISSUED, DELIVERY_MILESTONE,
                           CUSTOMER_ACCEPTANCE, RENEWAL),
                   reasons=("CANCELLED", "WITHDRAWN", "VOIDED", "REJECTED")),
}
STAGES = tuple(STAGE_RULES)

# Pipeline order for the reported status (furthest active milestone).
PIPELINE = (OPPORTUNITY_IDENTIFIED, PROBLEM_QUALIFIED, INTEREST_CONFIRMED, PROPOSAL_SENT, CONTRACT_SIGNED,
            INVOICE_ISSUED, DELIVERY_MILESTONE, CUSTOMER_ACCEPTANCE, VALUE_MEASURED)

REVENUE_NONE = "NONE"
REVENUE_UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
REVENUE_VERIFIED = "VERIFIED_NET_RETAINED"
REVENUE_FULLY_REVERSED = "FULLY_REVERSED"
REVENUE_HELD_IN_DISPUTE = "HELD_IN_DISPUTE"

REPEATABILITY_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
REPEATABILITY_CANDIDATE = "CANDIDATE_REQUIRES_HUMAN_PROMOTION"

_KEYS = frozenset(("stage", "engagement_ref", "account_ref") + _ALL_FIELDS)
_ENGAGEMENT_REF = re.compile(r"^eng-[a-z0-9][a-z0-9-]{2,62}$")
_ACCOUNT_REF = re.compile(r"^acct-[a-z0-9][a-z0-9-]{2,62}$")
_OFFER_REF = re.compile(r"^offer-[a-z0-9][a-z0-9-]{2,62}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_RECORD_ID = re.compile(r"^cxp-rec-[0-9a-f]{64}$")
MAX_MINOR = 10 ** 13
MAX_SUMMARY_CHARS = 500

# Free-text guard: refuses the obvious shapes of contact and banking data.
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_DIGIT_RUN = re.compile(r"\d[\d \-./]*\d")
_BANKING_WORDS = re.compile(r"\b(iban|swift|bic|routing|sort code|account number|card number|cvv|cvc|password)\b",
                            re.IGNORECASE)


def _refuse(code: str, detail: str):
    raise cxp.CXPError(code, detail)


def _check_summary(summary: str) -> None:
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        _refuse(cxp.E_MALFORMED, f"summary must be a non-empty string of at most {MAX_SUMMARY_CHARS} chars")
    if _EMAIL.search(summary) or _BANKING_WORDS.search(summary):
        _refuse(cxp.E_SENSITIVE_DATA, "summary appears to contain contact or banking details")
    for run in _DIGIT_RUN.findall(summary):
        if sum(ch.isdigit() for ch in run) >= 9:
            _refuse(cxp.E_SENSITIVE_DATA, "summary contains a long digit sequence (phone, card or account number?)")


def check_payload(payload: dict) -> None:
    """Strict schema for one COMMERCIAL_SIGNAL payload (called by cxp)."""
    if set(payload) != _KEYS:
        _refuse(cxp.E_MALFORMED, f"COMMERCIAL_SIGNAL payload requires exactly {sorted(_KEYS)}")
    stage = payload["stage"]
    if stage not in STAGE_RULES:
        _refuse(cxp.E_MALFORMED, f"unknown commercial stage {stage!r}")
    rules = STAGE_RULES[stage]
    if not isinstance(payload["engagement_ref"], str) or not _ENGAGEMENT_REF.match(payload["engagement_ref"]):
        _refuse(cxp.E_MALFORMED, "engagement_ref must look like eng-<lowercase-slug>")
    if not isinstance(payload["account_ref"], str) or not _ACCOUNT_REF.match(payload["account_ref"]):
        _refuse(cxp.E_MALFORMED, "account_ref must be an opaque acct-<lowercase-slug> pseudonym")
    for name in rules.get("required", ()):
        if payload[name] is None:
            _refuse(cxp.E_MALFORMED, f"{stage} requires {name}")
    for name in rules.get("forbidden", ()):
        if payload[name] is not None:
            _refuse(cxp.E_MALFORMED, f"{stage} must not carry {name}")
    if payload["offer_ref"] is not None and not (isinstance(payload["offer_ref"], str) and _OFFER_REF.match(payload["offer_ref"])):
        _refuse(cxp.E_MALFORMED, "offer_ref must look like offer-<lowercase-slug>")
    amount = payload["amount"]
    if amount is not None:
        if (not isinstance(amount, dict) or set(amount) != {"minor", "currency"}
                or not isinstance(amount["minor"], int) or isinstance(amount["minor"], bool)
                or not 0 <= amount["minor"] <= MAX_MINOR
                or not isinstance(amount["currency"], str) or not _CURRENCY.match(amount["currency"])):
            _refuse(cxp.E_MALFORMED, "amount must be {minor: non-negative integer, currency: ISO-4217 code}")
    for name in ("document_digest", "payment_reference_digest"):
        value = payload[name]
        if value is not None and not (isinstance(value, str) and _DIGEST.match(value)):
            _refuse(cxp.E_MALFORMED, f"{name} must be sha256:<64 hex> -- never a raw reference")
    if payload["target_record"] is not None and not (isinstance(payload["target_record"], str)
                                                      and _RECORD_ID.match(payload["target_record"])):
        _refuse(cxp.E_MALFORMED, "target_record must be a record id")
    reason = payload["reason"]
    if reason is not None and reason not in rules.get("reasons", ()):
        _refuse(cxp.E_MALFORMED, f"{stage} reason must be one of {rules.get('reasons', ())}")
    if payload["summary"] is not None:
        _check_summary(payload["summary"])


def check_labels(payload: dict, provenance: str, representation: str, verification: str, consent_ref) -> None:
    """Who may assert a stage, in what form (called by cxp's kind rules)."""
    rules = STAGE_RULES[payload["stage"]]
    if provenance not in rules.get("provenance", _HUMAN):
        _refuse(cxp.E_KIND_RULE, f"{payload['stage']} provenance must be one of {rules.get('provenance', _HUMAN)}")
    if representation not in rules.get("representation", _RECORDED):
        _refuse(cxp.E_KIND_RULE, f"{payload['stage']} representation must be one of {rules.get('representation', _RECORDED)}")
    if rules.get("never_verified") and verification != cxp.VER_UNVERIFIED:
        _refuse(cxp.E_KIND_RULE, f"an {payload['stage']} is a hypothesis and is never verified; record VALUE_MEASURED instead")
    if rules.get("consent") and consent_ref is None:
        _refuse(cxp.E_PRIVACY_CONSENT_REQUIRED, f"{payload['stage']} records a buyer conversation and needs a consent_ref")


def commerce_metadata(payload: dict) -> dict:
    """The payload-free index the exchange keeps for transition checks:
    pseudonymous refs and digests only, never amounts or text."""
    return {k: payload[k] for k in ("stage", "engagement_ref", "account_ref", "offer_ref", "target_record",
                                    "payment_reference_digest", "document_digest")}


# ---------------------------------------------------------------------------
# active-set computation shared by ingest checks and state derivation
# ---------------------------------------------------------------------------

def _active(records: dict) -> tuple:
    """records: {record_id: commerce metadata} for one engagement, erased
    records already excluded. Returns (active ids, voided {id: by},
    reversed {id: by}). A record is VOID if some non-void CORRECTION targets
    it (so correcting a correction restores the original), REVERSED if some
    active REVERSAL targets it. Content addressing makes correction chains
    acyclic; the recursion is bounded by the number of records anyway."""
    corrections = {}
    for rid, m in records.items():
        if m["stage"] == CORRECTION:
            corrections.setdefault(m["target_record"], []).append(rid)
    memo, visiting = {}, set()

    def void(rid):
        if rid in memo:
            return memo[rid]
        if rid in visiting:
            raise cxp.CXPError(cxp.E_KIND_RULE, "correction cycle")
        visiting.add(rid)
        memo[rid] = any(not void(c) for c in corrections.get(rid, ()))
        visiting.discard(rid)
        return memo[rid]

    voided = {rid: sorted(c for c in corrections[rid] if not void(c)) for rid in records if void(rid)}
    live = {rid for rid in records if rid not in voided}
    reversed_by = {}
    for rid in sorted(live):
        m = records[rid]
        if m["stage"] == REVERSAL and m["target_record"] in live:
            reversed_by.setdefault(m["target_record"], []).append(rid)
    active = {rid for rid in live
              if rid not in reversed_by and records[rid]["stage"] not in (CORRECTION, REVERSAL)}
    return active, voided, reversed_by


def _prerequisites_met(stage: str, payload_meta: dict, active_meta: list) -> bool:
    rules = STAGE_RULES[stage]
    stages_present = {m["stage"] for m in active_meta}
    if any(not set(group) & stages_present for group in rules.get("after", ())):
        return False
    if rules.get("after_payment"):
        return any(m["stage"] == PAYMENT_CONFIRMED and m["payment_reference_digest"] == payload_meta["payment_reference_digest"]
                   for m in active_meta)
    return True


def check_transition(record_meta: dict, all_records: dict, erased: set) -> None:
    """Ingest-time check (called by the exchange under its lock).
    record_meta: commerce metadata of the incoming record;
    all_records: {record_id: commerce metadata} for every accepted
    COMMERCIAL_SIGNAL record. Raises CXPError(TRANSITION_REFUSED)."""
    engagement = record_meta["engagement_ref"]
    mine = {rid: m for rid, m in all_records.items() if m["engagement_ref"] == engagement and rid not in erased}
    stage = record_meta["stage"]
    rules = STAGE_RULES[stage]

    accounts = {m["account_ref"] for m in mine.values()}
    if accounts and record_meta["account_ref"] not in accounts:
        _refuse(cxp.E_TRANSITION_REFUSED, "an engagement belongs to exactly one account_ref")
    digest = record_meta["payment_reference_digest"]
    if stage == PAYMENT_CONFIRMED:
        for rid, m in all_records.items():
            if m["payment_reference_digest"] == digest and m["engagement_ref"] != engagement:
                _refuse(cxp.E_TRANSITION_REFUSED, "this payment reference already belongs to another engagement")

    target = record_meta["target_record"]
    if target is not None:
        if target not in mine:
            _refuse(cxp.E_TRANSITION_REFUSED, "target_record is not an accepted, unerased record of this engagement")
        allowed = rules.get("target")
        if allowed != "ANY" and mine[target]["stage"] not in allowed:
            _refuse(cxp.E_TRANSITION_REFUSED, f"{stage} cannot target a {mine[target]['stage']}")

    active, _, _ = _active(mine)
    if stage == REVERSAL and target not in active:
        _refuse(cxp.E_TRANSITION_REFUSED, "only an active record can be reversed")
    if not _prerequisites_met(stage, record_meta, [mine[rid] for rid in active]):
        _refuse(cxp.E_TRANSITION_REFUSED, f"{stage} is not reachable from this engagement's current state")


# ---------------------------------------------------------------------------
# derived state
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PaymentPolicy:
    """Which VERIFICATION_RESULTs may confirm a payment. Supplied by the
    caller; approved_by names the human who set it (recorded, not
    authenticated). It governs what counts as revenue, never what may run."""

    policy_id: str
    approved_by: str
    admissible_provenance: tuple = (cxp.HUMAN_ASSERTED,)
    admissible_methods: tuple = ("payment-reconciliation",)

    def __post_init__(self):
        cxp._validate_identifier(self.policy_id, "policy_id")
        cxp._validate_identifier(self.approved_by, "approved_by")
        if not self.admissible_provenance or set(self.admissible_provenance) - {cxp.HUMAN_ASSERTED, cxp.AUTHORIZED_CONCLUSION}:
            raise ValueError("admissible_provenance must be a non-empty subset of HUMAN_ASSERTED, AUTHORIZED_CONCLUSION")
        if not self.admissible_methods or not all(isinstance(m, str) and m for m in self.admissible_methods):
            raise ValueError("admissible_methods must be non-empty strings")

    @property
    def grants_execution_authority(self) -> bool:
        return False


def _verification_verdict(exchange, record, policy) -> str:
    if record.verification != cxp.VER_VERIFIED:
        return "UNVERIFIED"
    if policy is None:
        return "NO_POLICY"
    result = exchange.record_metadata(record.verification_ref)
    if result is None or result["erased"]:
        return "VERIFICATION_ERASED"
    if result["provenance"] not in policy.admissible_provenance:
        return "PROVENANCE_NOT_ADMISSIBLE"
    if result.get("verification_method") not in policy.admissible_methods:
        return "METHOD_NOT_ADMISSIBLE"
    return "ADMISSIBLE"


def _add(totals: dict, amount: dict, sign: int = 1) -> None:
    totals[amount["currency"]] = totals.get(amount["currency"], 0) + sign * amount["minor"]


def _commercial_records(exchange, engagement_ref=None) -> dict:
    out = {}
    for meta in exchange.all_record_metadata():
        commerce = meta.get("commerce")
        if meta["kind"] == cxp.KIND_COMMERCIAL_SIGNAL and not meta["erased"] and (
                engagement_ref is None or commerce["engagement_ref"] == engagement_ref):
            out[meta["record_id"]] = commerce
    return out


def engagement_state(exchange, engagement_ref: str, policy: PaymentPolicy = None) -> dict:
    records = _commercial_records(exchange, engagement_ref)
    if not records:
        raise KeyError(engagement_ref)
    active, voided, reversed_by = _active(records)

    # A record whose prerequisites are no longer active (e.g. its contract
    # was voided) stops counting too; iterate to a fixpoint.
    counted = set(active)
    broken = set()
    while True:
        metas = [records[r] for r in counted]
        newly = {r for r in counted if not _prerequisites_met(records[r]["stage"], records[r], metas)}
        if not newly:
            break
        counted -= newly
        broken |= newly

    payloads = {rid: exchange.get_record(rid) for rid in sorted(records)}
    by_stage = {}
    for rid in sorted(counted):
        by_stage.setdefault(records[rid]["stage"], []).append(rid)

    def unique_amounts(stage, key):
        """Sum one amount per distinct document/payment digest; conflicting
        amounts for the same digest are reported and not summed."""
        groups = {}
        for rid in by_stage.get(stage, ()):
            p = payloads[rid].payload()
            groups.setdefault(p[key] or rid, set()).add((p["amount"]["minor"], p["amount"]["currency"]))
        totals, conflicts = {}, []
        for digest, amounts in sorted(groups.items()):
            if len(amounts) > 1:
                conflicts.append(digest)
            else:
                minor, currency = next(iter(amounts))
                _add(totals, {"minor": minor, "currency": currency})
        return totals, conflicts

    proposed, proposal_conflicts = unique_amounts(PROPOSAL_SENT, "document_digest")
    contracted, contract_conflicts = unique_amounts(CONTRACT_SIGNED, "document_digest")
    invoiced, invoice_conflicts = unique_amounts(INVOICE_ISSUED, "document_digest")
    measured, measure_conflicts = unique_amounts(VALUE_MEASURED, "document_digest")
    estimates = [{"record_id": rid, "reason": payloads[rid].payload()["reason"],
                  "amount": payloads[rid].payload()["amount"]} for rid in by_stage.get(ESTIMATE_RECORDED, ())]

    # payments, grouped by payment reference digest
    payment_groups, inadmissible, unverified = {}, [], []
    for rid in by_stage.get(PAYMENT_CONFIRMED, ()):
        record = payloads[rid]
        p = record.payload()
        group = payment_groups.setdefault(p["payment_reference_digest"], {"amounts": set(), "verified_by": []})
        group["amounts"].add((p["amount"]["minor"], p["amount"]["currency"]))
        verdict = _verification_verdict(exchange, record, policy)
        if verdict == "ADMISSIBLE":
            group["verified_by"].append(rid)
        elif verdict == "UNVERIFIED":
            unverified.append(rid)
        else:
            inadmissible.append({"record_id": rid, "reason": verdict})
    payment_conflicts, verified_payments = [], {}
    for digest, group in sorted(payment_groups.items()):
        if len(group["amounts"]) > 1:
            payment_conflicts.append(digest)
        elif group["verified_by"]:
            minor, currency = next(iter(group["amounts"]))
            verified_payments[digest] = {"minor": minor, "currency": currency}

    gross, refunded, dispute_lost, held = {}, {}, {}, {}
    anomalies = []
    for digest, amount in verified_payments.items():
        _add(gross, amount)
    lost_disputes = {records[r]["target_record"] for r in by_stage.get(DISPUTE_RESOLVED, ())
                     if payloads[r].payload()["reason"] == "LOST"}
    resolved_disputes = {records[r]["target_record"] for r in by_stage.get(DISPUTE_RESOLVED, ())}
    deductions = {}
    for stage in (REFUND_ISSUED, DISPUTE_OPENED):
        for rid in by_stage.get(stage, ()):
            p = payloads[rid].payload()
            paid = verified_payments.get(p["payment_reference_digest"])
            if paid is None or paid["currency"] != p["amount"]["currency"]:
                anomalies.append({"record_id": rid, "issue": "TARGETS_NO_VERIFIED_PAYMENT_IN_THIS_CURRENCY"})
                continue
            if stage == REFUND_ISSUED:
                target_bucket = refunded
            elif rid in lost_disputes:
                target_bucket = dispute_lost
            elif rid in resolved_disputes:
                continue  # won: the money stays
            else:
                target_bucket = held
            already = deductions.get(p["payment_reference_digest"], 0)
            take = min(p["amount"]["minor"], paid["minor"] - already)
            if take < p["amount"]["minor"]:
                anomalies.append({"record_id": rid, "issue": "EXCEEDS_REMAINING_PAYMENT"})
            deductions[p["payment_reference_digest"]] = already + take
            _add(target_bucket, {"minor": take, "currency": paid["currency"]})
    net = {c: gross.get(c, 0) - refunded.get(c, 0) - dispute_lost.get(c, 0) - held.get(c, 0) for c in gross}

    if any(v > 0 for v in net.values()):
        revenue_status = REVENUE_VERIFIED
    elif any(v > 0 for v in held.values()):
        revenue_status = REVENUE_HELD_IN_DISPUTE
    elif gross:
        revenue_status = REVENUE_FULLY_REVERSED
    elif unverified or inadmissible or payment_conflicts:
        revenue_status = REVENUE_UNVERIFIED_CLAIM
    else:
        revenue_status = REVENUE_NONE

    reached = [s for s in PIPELINE if s in by_stage]
    flags = sorted({s for s in (LOST, CHURNED) if s in by_stage}
                   | ({"DISPUTE_OPEN"} if any(held.values()) else set())
                   | ({"PAYMENT_CONFLICT"} if payment_conflicts else set())
                   | ({"AMOUNT_CONFLICT"} if proposal_conflicts or contract_conflicts or invoice_conflicts
                      or measure_conflicts else set()))
    return {
        "engagement_ref": engagement_ref,
        "account_ref": next(iter(records.values()))["account_ref"],
        "status": reached[-1] if reached else None,
        "flags": flags,
        "milestones": by_stage,
        "hypotheses": {"estimates": estimates, "proposed": proposed,
                       "label": "HYPOTHESES_AND_OFFERS_ARE_NOT_REVENUE"},
        "contracted": contracted,
        "invoiced": invoiced,
        "revenue": {
            "status": revenue_status,
            "verified_gross": gross, "refunded": refunded, "dispute_lost": dispute_lost,
            "held_in_open_dispute": held, "net_retained": net,
            "unverified_payment_records": sorted(unverified),
            "inadmissible_payment_records": inadmissible,
            "conflicting_payment_references": payment_conflicts,
            "anomalies": anomalies,
        },
        "measured_value": measured,
        "voided": {rid: by for rid, by in sorted(voided.items())},
        "reversed": {rid: by for rid, by in sorted(reversed_by.items())},
        "prerequisite_broken": sorted(broken),
        "policy_id": None if policy is None else policy.policy_id,
        "grants_execution_authority": False,
    }


def repeatability(exchange, offer_ref: str, policy: PaymentPolicy = None, minimum_independent_buyers: int = 3) -> dict:
    """Whether an offer has been bought, accepted and measured by enough
    INDEPENDENT buyers to be put to a human as a repeatable-capability
    candidate. Independence: different account_refs AND no shared evidence
    origin (R2 lineage) between their engagements' records; engagements
    linked by either are counted as one buyer. Never returns 'proven'."""
    if not isinstance(minimum_independent_buyers, int) or minimum_independent_buyers < 2:
        raise ValueError("minimum_independent_buyers must be an integer >= 2")
    records = _commercial_records(exchange)
    engagements = sorted({m["engagement_ref"] for m in records.values() if m["offer_ref"] == offer_ref})
    qualifying, rejected = [], []
    for eng in engagements:
        state = engagement_state(exchange, eng, policy)
        missing = [name for name, ok in (
            ("verified_net_retained_revenue", state["revenue"]["status"] == REVENUE_VERIFIED),
            ("customer_acceptance", CUSTOMER_ACCEPTANCE in state["milestones"]),
            ("measured_value", VALUE_MEASURED in state["milestones"])) if not ok]
        (rejected if missing else qualifying).append({"engagement_ref": eng, "account_ref": state["account_ref"],
                                                      "missing": missing})

    # union-find over shared accounts and shared evidence origins
    parent = {q["engagement_ref"]: q["engagement_ref"] for q in qualifying}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owners = {}
    for q in qualifying:
        eng = q["engagement_ref"]
        keys = {("account", q["account_ref"])}
        for rid, m in records.items():
            if m["engagement_ref"] == eng:
                for source in lineage.trace(exchange.record_metadata, rid)["sources"]:
                    keys.add(("origin", source["origin"]))
        for key in keys:
            if key in owners:
                parent[find(eng)] = find(owners[key])
            else:
                owners[key] = eng
    groups = {}
    for q in qualifying:
        groups.setdefault(find(q["engagement_ref"]), []).append(q["engagement_ref"])
    independent = len(groups)
    return {
        "offer_ref": offer_ref,
        "status": REPEATABILITY_CANDIDATE if independent >= minimum_independent_buyers else REPEATABILITY_INSUFFICIENT,
        "independent_buyers": independent,
        "minimum_independent_buyers": minimum_independent_buyers,
        "buyer_groups": sorted(sorted(g) for g in groups.values()),
        "qualifying_engagements": sorted(q["engagement_ref"] for q in qualifying),
        "non_qualifying_engagements": rejected,
        "promotion_requires_human_decision": True,
        "policy_id": None if policy is None else policy.policy_id,
        "grants_execution_authority": False,
    }
