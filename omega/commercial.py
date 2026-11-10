"""Commercial continuity (Stage G).

Every commercial fact is a COMMERCE_SIGNAL or PAYMENT_VERIFIED event. The
deal state is DERIVED from all of them on every call; nothing is edited.

Distinctions kept apart (each is its own flag, never inferred from another):
    interest expressed  !=  verbal agreement  !=  written agreement
    invoice issued      !=  payment attempted !=  payment CLAIMED by customer
    payment claimed     !=  payment CONFIRMED (needs PAYMENT_VERIFIED: a human,
                            a bank / processor settlement record artifact, and
                            a reference that matches an invoice / attempt / claim)
    work authorized     (needs a written agreement first)
    deliverable submitted != deliverable accepted (needs a customer-originated
                            source) != obligation completed

This mirrors, and does not replace, cognition/commerce.py (the CXP
engagement state machine used on the forge node; see ADR-0003). A customer's
statement that they paid can only ever produce PAYMENT_CLAIMED.
"""
from __future__ import annotations

from typing import Optional

from omega.events import event_id_for
from omega.store import StoreError

PREREQ = {
    "WORK_AUTHORIZED": ("WRITTEN_AGREEMENT",),
    "DELIVERABLE_ACCEPTED": ("DELIVERABLE_SUBMITTED",),
    "OBLIGATION_COMPLETED": ("DELIVERABLE_ACCEPTED",),
}


def deal_entity(deal_id: str) -> str:
    return f"deal:{deal_id}"


class CommercialLedger:
    def __init__(self, node):
        self.node = node

    def _events(self, deal_id):
        return [e for e in self.node.events(entity=deal_entity(deal_id))
                if e.header["event_type"] in ("COMMERCE_SIGNAL", "PAYMENT_VERIFIED") and e.payload is not None]

    def record(self, deal_id: str, stage: str, summary: str, *, actor: str, source_ref: str,
               amount_minor: Optional[int] = None, currency: Optional[str] = None,
               reference: Optional[str] = None, due: Optional[str] = None, contact_id: Optional[str] = None,
               document: Optional[bytes] = None, document_type: str = "application/pdf"):
        have = {e.payload["stage"] for e in self._events(deal_id) if e.header["event_type"] == "COMMERCE_SIGNAL"}
        for req in PREREQ.get(stage, ()):
            if req not in have:
                raise StoreError("TRANSITION_REFUSED", f"{stage} requires {req} first")
        payload = {"deal_id": deal_id, "stage": stage, "summary": summary}
        for k, v in (("amount_minor", amount_minor), ("currency", currency), ("reference", reference), ("due", due)):
            if v is not None:
                payload[k] = v
        links = [deal_entity(deal_id)] + ([f"contact:{contact_id}"] if contact_id else [])
        return self.node.append("COMMERCE_SIGNAL", payload, actor=actor, links=links, privacy="PRIVATE",
                                provenance=[{"kind": "source", "ref": source_ref}],
                                artifact_data=[(document, document_type)] if document is not None else None)

    def verify_payment(self, deal_id: str, *, reference: str, amount_minor: int, currency: str,
                       settlement_source: str, settlement_record: bytes, actor: str,
                       record_type: str = "application/pdf"):
        refs = {e.payload.get("reference") for e in self._events(deal_id)
                if e.header["event_type"] == "COMMERCE_SIGNAL"
                and e.payload["stage"] in ("INVOICE_ISSUED", "PAYMENT_ATTEMPTED", "PAYMENT_CLAIMED")}
        if reference not in refs:
            raise StoreError("TRANSITION_REFUSED", f"no invoice / attempt / claim with reference {reference!r}")
        return self.node.append("PAYMENT_VERIFIED",
                                {"deal_id": deal_id, "reference": reference, "amount_minor": amount_minor,
                                 "currency": currency, "settlement_source": settlement_source},
                                actor=actor, links=[deal_entity(deal_id)], privacy="PRIVATE", verification="VERIFIED",
                                provenance=[{"kind": "source", "ref": f"settlement:{settlement_source}:{reference}"}],
                                artifact_data=[(settlement_record, record_type)])

    def deal_state(self, deal_id: str, today: Optional[str] = None) -> dict:
        evs = self._events(deal_id)
        sig = [e for e in evs if e.header["event_type"] == "COMMERCE_SIGNAL"]
        ver = [e for e in evs if e.header["event_type"] == "PAYMENT_VERIFIED"]
        stages = {e.payload["stage"] for e in sig}

        def total(stage):
            return sum(e.payload.get("amount_minor", 0) for e in sig if e.payload["stage"] == stage)

        invoiced = total("INVOICE_ISSUED")
        verified = sum(e.payload["amount_minor"] for e in ver)
        state = {
            "deal_id": deal_id,
            "lead": "LEAD_RECORDED" in stages,
            "interest_expressed": "INTEREST_EXPRESSED" in stages,
            "proposal_sent": "PROPOSAL_SENT" in stages,
            "verbal_agreement": "VERBAL_AGREEMENT" in stages,
            "written_agreement": "WRITTEN_AGREEMENT" in stages,
            "invoice_issued": "INVOICE_ISSUED" in stages,
            "payment_attempted": "PAYMENT_ATTEMPTED" in stages,
            "payment_claimed": "PAYMENT_CLAIMED" in stages,
            "payment_confirmed": bool(ver),
            "work_authorized": "WORK_AUTHORIZED" in stages,
            "deliverable_submitted": "DELIVERABLE_SUBMITTED" in stages,
            "deliverable_accepted": "DELIVERABLE_ACCEPTED" in stages,
            "obligation_completed": "OBLIGATION_COMPLETED" in stages,
            "amounts_minor": {"invoiced": invoiced, "claimed_paid": total("PAYMENT_CLAIMED"),
                              "verified_paid": verified, "outstanding": max(invoiced - verified, 0)},
            "evidence": sorted(event_id_for(e.header) for e in evs),
        }
        warnings = []
        if state["payment_claimed"] and not state["payment_confirmed"]:
            warnings.append("PAYMENT_CLAIMED_NOT_VERIFIED")
        if state["verbal_agreement"] and not state["written_agreement"]:
            warnings.append("VERBAL_ONLY_NO_WRITTEN_AGREEMENT")
        if state["deliverable_submitted"] and not state["deliverable_accepted"]:
            warnings.append("AWAITING_CUSTOMER_ACCEPTANCE")
        today = today or self.node.clock()[:10]
        follow = [{"summary": e.payload["summary"], "due": e.payload.get("due"),
                   "overdue": bool(e.payload.get("due") and e.payload["due"] < today)}
                  for e in sig if e.payload["stage"] == "FOLLOW_UP_COMMITTED"]
        if any(f["overdue"] for f in follow):
            warnings.append("FOLLOW_UP_OVERDUE")
        state["follow_ups"] = follow
        state["warnings"] = warnings
        return state
