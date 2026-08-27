"""Deterministic, auditable intent/signal/risk classifier (mission Section 9).

Rule-based by design for this increment: classification decisions gate real
commercial/authority consequences, and no AI-routing credentials were
confirmed for this channel (see governance/02_ADR.md). The extension point
below shows where AI-assisted classification would plug in through the
existing router/mission_router.py once the operator wants that, with logged
evidence rather than an unverifiable black box.

Message content is treated strictly as data: nothing in this module executes
instructions found inside a message, regardless of what the text claims
about roles, permissions, or system state (mitigates prompt injection, T3 in
the threat model).
"""
import re

PRICING_WORDS = {"price", "pricing", "cost", "quote", "how much", "rate"}
SCHEDULING_WORDS = {"schedule", "meeting", "appointment", "call", "available", "book"}
OBJECTION_WORDS = {"too expensive", "not sure", "don't think", "disappointed", "unhappy", "complaint", "refund"}
REFERRAL_WORDS = {"refer", "referral", "recommend you", "sent me", "friend of"}
URGENCY_WORDS = {"urgent", "asap", "emergency", "immediately", "right now", "today"}
SUPPORT_WORDS = {"broken", "not working", "issue", "problem", "bug", "error", "help"}
FEEDBACK_WORDS = {"feedback", "suggestion", "review", "rating"}

SENSITIVE_PATTERNS = [
    re.compile(r"\b\d{13,19}\b"),               # payment-card-like number
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),        # SSN-like
    re.compile(r"\bpassword\b", re.IGNORECASE),
]


def _contains_any(text: str, words) -> bool:
    lowered = text.lower()
    return any(w in lowered for w in words)


def _extract_text(event: dict, raw_text: str = None) -> str:
    return raw_text or ""


def classify(event: dict, raw_text: str = None, thread_context: dict = None) -> dict:
    text = _extract_text(event, raw_text)
    thread_context = thread_context or {}

    intent = []
    signals = []
    risk_flags = []

    if event.get("message_type") == "status":
        return {
            "summary": "delivery status update",
            "intent": ["delivery_status"],
            "urgency": "low",
            "opportunity_score": 0,
            "risk_level": "low",
            "evidence_sufficiency": "sufficient",
            "recommended_action": "reconcile_delivery_status",
            "response_strategy": "none",
            "approval_requirement": "none",
            "follow_up_at": None,
            "confidence": 1.0,
            "supporting_event_ids": [event["event_id"]],
        }

    if _contains_any(text, PRICING_WORDS):
        intent.append("pricing_inquiry")
        signals.append("buying_signal")
    if _contains_any(text, SCHEDULING_WORDS):
        intent.append("scheduling_request")
        signals.append("buying_signal")
    if _contains_any(text, OBJECTION_WORDS):
        intent.append("objection")
        signals.append("objection_pattern")
    if _contains_any(text, REFERRAL_WORDS):
        intent.append("referral")
        signals.append("referral_pathway")
    if _contains_any(text, SUPPORT_WORDS):
        intent.append("support_request")
        signals.append("workflow_failure_signal")
    if _contains_any(text, FEEDBACK_WORDS):
        intent.append("feedback")
    if not intent:
        intent.append("general_inquiry")

    urgency = "high" if _contains_any(text, URGENCY_WORDS) else "normal"
    if "objection" in intent:
        urgency = "high"

    sensitive = any(p.search(text) for p in SENSITIVE_PATTERNS)
    if sensitive:
        risk_flags.append("sensitive_data_present")

    risk_level = "high" if sensitive else ("medium" if "objection" in intent else "low")

    opportunity_score = 0
    if "pricing_inquiry" in intent:
        opportunity_score += 40
    if "scheduling_request" in intent:
        opportunity_score += 30
    if "referral" in intent:
        opportunity_score += 20
    if signals:
        opportunity_score += 10
    opportunity_score = min(opportunity_score, 100)

    # Evidence sufficiency: can we act on this without more information?
    has_prior_context = bool(thread_context.get("prior_messages"))
    if sensitive:
        evidence_sufficiency = "insufficient"  # never draft on sensitive content without escalation
    elif intent[0] == "general_inquiry" and not has_prior_context:
        evidence_sufficiency = "partial"
    else:
        evidence_sufficiency = "sufficient"

    approval_requirement = "none"
    if "pricing_inquiry" in intent:
        approval_requirement = "send_pricing"
    elif "scheduling_request" in intent:
        approval_requirement = "send_scheduling_commitment"
    elif event.get("direction") == "inbound":
        approval_requirement = "send_generated_answer"

    recommended_action = "draft_response"
    if sensitive:
        recommended_action = "escalate_to_person"
    elif "objection" in intent:
        recommended_action = "draft_response_and_flag_for_review"

    return {
        "summary": f"inbound message classified as {', '.join(intent)}",
        "intent": intent,
        "urgency": urgency,
        "opportunity_score": opportunity_score,
        "risk_level": risk_level,
        "evidence_sufficiency": evidence_sufficiency,
        "recommended_action": recommended_action,
        "response_strategy": "template_first_contact" if not has_prior_context else "continue_thread",
        "approval_requirement": approval_requirement,
        "follow_up_at": None,
        "confidence": 0.6,  # rule-based classifier; not a calibrated model, kept conservative
        "supporting_event_ids": [event["event_id"]],
        "risk_flags": risk_flags,
    }


# Extension point: route to AI-assisted classification via the existing
# capability router once the operator wants it, with a required evidence
# trail (never silently swap the deterministic path for a model call):
#
#   from router import mission_router
#   decision = mission_router.route(objective="classify_whatsapp_message",
#                                    required_tags=["classification"])
#
# Not wired in this increment -- no credentials/evidence exist yet to
# justify preferring it over the deterministic classifier above.
