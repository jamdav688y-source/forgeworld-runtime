"""Closed vocabularies and governance rules (FW-SCS-001 rules 7, 9, 11, 12).

This module is the single place that says WHO may assert WHAT. It is data,
checked by events.validate(); agents and models cannot change it at run
time, and any event in the GOVERNANCE scope from a non-human actor is
refused. Changing this file is a code change that must pass the promotion
gate (evolution.PromotionGate pins its hash).
"""
from __future__ import annotations

ACTOR_KINDS = ("HUMAN", "MODEL", "TOOL", "SYSTEM")

# Ordered privacy classes. DEVICE_LOCAL never leaves the device that wrote
# it (only its signed header is shared, so sequence continuity still holds).
PRIVACY_ORDER = ("PUBLIC", "INTERNAL", "PRIVATE", "SECRET")
DEVICE_LOCAL = "DEVICE_LOCAL"
PRIVACY_CLASSES = PRIVACY_ORDER + (DEVICE_LOCAL,)

VERIFICATION_STATES = ("UNVERIFIED", "VERIFIED", "CONTESTED", "REFUTED")

SCOPES = ("memory", "relationship", "commerce", "task", "sync", "governance",
          "evolution", "forge")


def privacy_allows(event_privacy: str, max_privacy: str) -> bool:
    """True if an event of `event_privacy` may be shared with a peer cleared
    up to `max_privacy`."""
    if event_privacy == DEVICE_LOCAL:
        return False
    return PRIVACY_ORDER.index(event_privacy) <= PRIVACY_ORDER.index(max_privacy)


# event_type -> (allowed actor kinds, required scope)
EVENT_TYPES = {
    "ARTIFACT_INGESTED":     (("HUMAN", "TOOL", "SYSTEM"), "memory"),
    "NOTE_RECORDED":         (("HUMAN", "TOOL", "SYSTEM", "MODEL"), "memory"),
    "PROJECT_ASSERTED":      (("HUMAN",), "memory"),
    "CONTACT_ASSERTED":      (("HUMAN", "TOOL"), "relationship"),
    "MESSAGE_RECORDED":      (("HUMAN", "TOOL"), "relationship"),
    "FACT_ASSERTED":         (("HUMAN", "TOOL", "MODEL"), "relationship"),
    "COMMITMENT_RECORDED":   (("HUMAN", "TOOL"), "relationship"),
    "COMMITMENT_STATUS":     (("HUMAN",), "relationship"),
    "DRAFT_PRODUCED":        (("TOOL", "MODEL", "SYSTEM"), "relationship"),
    "COMMERCE_SIGNAL":       (("HUMAN", "TOOL"), "commerce"),
    "PAYMENT_VERIFIED":      (("HUMAN",), "commerce"),
    "TASK_QUEUED":           (("HUMAN", "TOOL", "MODEL", "SYSTEM"), "task"),
    "TASK_AUTHORIZED":       (("HUMAN",), "task"),
    "TASK_RESULT":           (("SYSTEM", "TOOL"), "task"),
    "PEER_PAIRED":           (("HUMAN",), "sync"),
    "ACCESS_REVOKED":        (("HUMAN",), "sync"),
    "DELETION_AUTHORIZED":   (("HUMAN",), "governance"),
    "RETENTION_POLICY":      (("HUMAN",), "governance"),
    "CONFLICT_RESOLVED":     (("HUMAN",), "governance"),
    "BENCHMARK_RESULT":      (("TOOL", "SYSTEM"), "forge"),
    "AGENT_OPINION":         (("MODEL", "TOOL"), "forge"),
    "EXPERIMENT_RECORDED":   (("HUMAN", "TOOL", "SYSTEM", "MODEL"), "evolution"),
    "PROMOTION_DECISION":    (("HUMAN",), "evolution"),
}

# Model output is never evidence of verification: a non-human event may
# only be written UNVERIFIED.
NON_HUMAN_MAX_VERIFICATION = "UNVERIFIED"

# Commercial stages, deliberately distinct (Stage G).
COMMERCE_STAGES = (
    "LEAD_RECORDED",          # a lead / prospect exists
    "INTEREST_EXPRESSED",     # they said they are interested
    "PROPOSAL_SENT",
    "VERBAL_AGREEMENT",       # said yes; not binding evidence
    "WRITTEN_AGREEMENT",      # needs a signed-document artifact
    "INVOICE_ISSUED",
    "PAYMENT_ATTEMPTED",      # a payment was initiated (e.g. link opened)
    "PAYMENT_CLAIMED",        # the customer SAYS they paid
    "WORK_AUTHORIZED",        # needs a written agreement
    "DELIVERABLE_SUBMITTED",
    "DELIVERABLE_ACCEPTED",   # needs a customer-originated source
    "OBLIGATION_COMPLETED",
    "FOLLOW_UP_COMMITTED",
)
# Only these stages may come from a tool import; every other stage requires a
# human assertion.
COMMERCE_TOOL_STAGES = ("LEAD_RECORDED", "INTEREST_EXPRESSED", "PAYMENT_CLAIMED")
SETTLEMENT_SOURCES = ("bank_statement", "processor_record")
