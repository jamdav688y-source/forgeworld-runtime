"""Response compiler (mission Section 10).

Produces a draft object carrying full internal reasoning (intended outcome,
claims used, evidence, assumptions, avoided commitments, required authority,
confidence) plus a natural user-facing message. Never sends; always writes
READY_FOR_HUMAN_APPROVAL to the execution ledger.
"""
import time
import uuid
from pathlib import Path

from . import authority, ledger

MODULE_ROOT = Path(__file__).resolve().parent.parent
MEMORY_LOG = MODULE_ROOT.parent / "memory" / "memory.log"

TEMPLATES = {
    "pricing_inquiry": (
        "Thanks for asking! I want to make sure I quote this accurately for your situation, "
        "so let me have someone from ForgeWorld confirm pricing details with you shortly."
    ),
    "scheduling_request": (
        "Happy to set that up. Let me check available times and confirm a slot with you shortly."
    ),
    "support_request": (
        "Sorry you're running into that. Can you tell me a bit more about what's happening so "
        "we can help fix it?"
    ),
    "objection": (
        "I hear you, and I want to make sure we address this properly rather than rushing a "
        "response. Someone will follow up with you shortly."
    ),
    "referral": (
        "Thank you so much for the referral, that means a lot! I'll make sure it's noted."
    ),
    "feedback": "Thanks for the feedback, I really appreciate you taking the time to share it.",
    "general_inquiry": "Thanks for reaching out! Could you tell me a little more about what you need?",
}


def _read_memory_context(limit_lines: int = 20) -> list:
    if not MEMORY_LOG.exists():
        return []
    lines = MEMORY_LOG.read_text().splitlines()
    return lines[-limit_lines:]


def compile_draft(event: dict, classification: dict, thread_context: dict = None) -> dict:
    thread_context = thread_context or {}
    primary_intent = classification["intent"][0] if classification["intent"] else "general_inquiry"
    action = classification.get("approval_requirement", "send_generated_answer")
    if action == "none":
        action = "send_generated_answer"

    message_text = TEMPLATES.get(primary_intent, TEMPLATES["general_inquiry"])

    prohibited_avoided = []
    if primary_intent == "pricing_inquiry":
        prohibited_avoided.append("did not state a specific price without human approval")
    if primary_intent == "scheduling_request":
        prohibited_avoided.append("did not confirm a specific time slot without human approval")
    if classification.get("risk_level") == "high":
        prohibited_avoided.append("did not respond to sensitive content automatically")

    draft = {
        "draft_id": str(uuid.uuid4()),
        "event_id": event["event_id"],
        "conversation_id": event["conversation_id"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": message_text,
        "reasoning": {
            "intended_outcome": f"acknowledge and move '{primary_intent}' forward without overcommitting",
            "factual_claims_used": [],
            "evidence": classification.get("supporting_event_ids", []),
            "assumptions": ["sender is the verified WhatsApp contact for this conversation_id"],
            "prohibited_commitments_avoided": prohibited_avoided,
            "authority_required": action,
            "suggested_follow_up": classification.get("recommended_action"),
            "confidence": classification.get("confidence", 0.5),
        },
        "action": action,
        "required_authority_tier": authority.required_authority(action),
        "authority_state": "draft",
        "terminal_state": "READY_FOR_HUMAN_APPROVAL",
    }

    ledger.append(ledger.EXECUTION_LEDGER, {
        "trace_id": event.get("processing_trace_id"),
        "draft_id": draft["draft_id"],
        "event_id": event["event_id"],
        "state": "READY_FOR_HUMAN_APPROVAL",
        "action": action,
        "recorded_at": draft["created_at"],
    })

    return draft
