"""Stage G: commercial payment-state accuracy and distinct milestones."""
import pytest

from omega.commercial import CommercialLedger
from omega.store import StoreError
from omega.tests.conftest import HUMAN


def test_customer_statement_of_payment_is_never_settlement(phone):
    led = CommercialLedger(phone)
    led.record("deal-1", "INTEREST_EXPRESSED", "asked for a quote", actor="tool:sms-import", source_ref="sms:dana#2")
    led.record("deal-1", "VERBAL_AGREEMENT", "said yes on the call", actor=HUMAN, source_ref="call:2026-11-02")
    s = led.deal_state("deal-1")
    assert s["verbal_agreement"] and not s["written_agreement"]
    assert "VERBAL_ONLY_NO_WRITTEN_AGREEMENT" in s["warnings"]
    led.record("deal-1", "WRITTEN_AGREEMENT", "signed SOW", actor=HUMAN, source_ref="file:sow.pdf", document=b"%PDF signed")
    led.record("deal-1", "INVOICE_ISSUED", "invoice 001", actor=HUMAN, source_ref="invoice:001",
               amount_minor=500000, currency="USD", reference="INV-001")
    led.record("deal-1", "PAYMENT_CLAIMED", "customer: 'I just paid it'", actor="tool:sms-import",
               source_ref="sms:dana#9", amount_minor=500000, currency="USD", reference="INV-001")
    s = led.deal_state("deal-1")
    assert s["payment_claimed"] and not s["payment_confirmed"]
    assert s["amounts_minor"] == {"invoiced": 500000, "claimed_paid": 500000, "verified_paid": 0, "outstanding": 500000}
    assert "PAYMENT_CLAIMED_NOT_VERIFIED" in s["warnings"]
    led.verify_payment("deal-1", reference="INV-001", amount_minor=500000, currency="USD",
                       settlement_source="bank_statement", settlement_record=b"bank line 2026-11-04 +5000.00", actor=HUMAN,
                       operator=phone.op)
    s = led.deal_state("deal-1")
    assert s["payment_confirmed"] and s["amounts_minor"]["outstanding"] == 0
    assert "PAYMENT_CLAIMED_NOT_VERIFIED" not in s["warnings"]


def test_only_humans_with_evidence_can_confirm(phone):
    led = CommercialLedger(phone)
    led.record("d", "INVOICE_ISSUED", "inv", actor=HUMAN, source_ref="invoice:1", amount_minor=100, currency="USD",
               reference="R1")
    with pytest.raises(StoreError) as e:
        led.verify_payment("d", reference="R1", amount_minor=100, currency="USD", settlement_source="bank_statement",
                           settlement_record=b"x", actor="tool:bank-scraper")
    assert e.value.code == "ACTOR_NOT_PERMITTED"
    with pytest.raises(StoreError) as e:
        led.verify_payment("d", reference="R-unknown", amount_minor=100, currency="USD",
                           settlement_source="bank_statement", settlement_record=b"x", actor=HUMAN, operator=phone.op)
    assert e.value.code == "TRANSITION_REFUSED"
    with pytest.raises(StoreError) as e:
        led.record("d", "VERBAL_AGREEMENT", "model thinks they agreed", actor="model:llm", source_ref="x")
    assert e.value.code == "ACTOR_NOT_PERMITTED"


def test_milestone_prerequisites(phone):
    led = CommercialLedger(phone)
    with pytest.raises(StoreError):
        led.record("d", "WORK_AUTHORIZED", "start", actor=HUMAN, source_ref="x")
    with pytest.raises(StoreError) as e:
        led.record("d", "WRITTEN_AGREEMENT", "no doc attached", actor=HUMAN, source_ref="x")
    assert e.value.code == "PROVENANCE_MISSING"
    led.record("d", "WRITTEN_AGREEMENT", "signed", actor=HUMAN, source_ref="file:c.pdf", document=b"pdf")
    led.record("d", "WORK_AUTHORIZED", "start", actor=HUMAN, source_ref="email:go")
    with pytest.raises(StoreError):
        led.record("d", "DELIVERABLE_ACCEPTED", "ok", actor=HUMAN, source_ref="customer:email/1")
    led.record("d", "DELIVERABLE_SUBMITTED", "sent v1", actor=HUMAN, source_ref="email:out/2")
    assert "AWAITING_CUSTOMER_ACCEPTANCE" in led.deal_state("d")["warnings"]
    with pytest.raises(StoreError) as e:
        led.record("d", "DELIVERABLE_ACCEPTED", "I think they liked it", actor=HUMAN, source_ref="operator:guess")
    assert e.value.code == "PROVENANCE_MISSING"
    led.record("d", "DELIVERABLE_ACCEPTED", "approved in writing", actor=HUMAN, source_ref="customer:email/3")
    led.record("d", "OBLIGATION_COMPLETED", "closed", actor=HUMAN, source_ref="operator:close")
    s = led.deal_state("d")
    assert s["deliverable_accepted"] and s["obligation_completed"] and not s["payment_confirmed"]


def test_follow_up_overdue(phone):
    led = CommercialLedger(phone)
    led.record("d", "FOLLOW_UP_COMMITTED", "send revised quote", actor=HUMAN, source_ref="call:1", due="2026-11-03")
    assert "FOLLOW_UP_OVERDUE" in led.deal_state("d", today="2026-11-10")["warnings"]
