"""Authority enforcement, matching governance/05_AUTHORITY_MATRIX.md exactly.

This is the single place that decides whether an action may proceed. Message
content, classifier output, and draft text are all treated as untrusted
input to this decision -- only the CLI (a human) writing an approval record,
or an operator-edited config.json grant, can move an action from
'requires_approval'/'prohibited' to executable.
"""
from . import ledger, modes

AUTO_ACTIONS = {
    "webhook_verify", "dedupe", "schema_validate", "consent_lookup", "classify",
    "summarize", "draft_create", "ledger_write", "internal_notify_low_risk",
    "followup_recommend", "delivery_status_reconcile", "metric_calculate",
    "stopword_revoke_consent",
}

APPROVAL_ACTIONS = {
    "first_outbound_contact", "send_generated_answer", "claim_forgeworld_performance",
    "send_pricing", "send_discount", "send_proposal", "send_scheduling_commitment",
    "send_customer_recommendation", "publish", "escalate_to_person",
    "process_unclear_sensitive_material", "change_template", "change_campaign_audience",
    "enable_higher_autonomy",
}

PROHIBITED_ACTIONS = {
    "payment_or_refund", "contract", "legal_medical_financial_conclusion",
    "delete_evidence", "export_contact_list", "mass_outreach", "identity_impersonation",
    "undisclosed_surveillance", "bypass_optin", "autonomous_promise", "train_general_ai",
    "unrelated_marketing", "contact_inferred_recipient",
}

ALL_ACTIONS = AUTO_ACTIONS | APPROVAL_ACTIONS | PROHIBITED_ACTIONS


def required_authority(action: str) -> str:
    if action in AUTO_ACTIONS:
        return "auto"
    if action in APPROVAL_ACTIONS:
        return "approval"
    if action in PROHIBITED_ACTIONS:
        return "prohibited"
    raise ValueError(f"unknown action '{action}' is not in the authority matrix")


def has_grant(action: str, config: dict = None) -> bool:
    config = config or modes.load_config()
    grants = config.get("authority", {}).get("grants", [])
    return any(g["action"] == action for g in grants)


def check_send_authorized(
    action: str,
    approval_record: dict,
    consent: dict,
    config: dict = None,
) -> tuple:
    """Returns (authorized: bool, blocker: str|None)."""
    config = config or modes.load_config()
    tier = required_authority(action)

    if tier == "prohibited" and not has_grant(action, config):
        return False, "BLOCKED_BY_AUTHORITY"

    if modes.is_outbound_blocked():
        return False, "BLOCKED_BY_AUTHORITY"

    if consent.get("consent_state") == "revoked":
        return False, "BLOCKED_BY_CONSENT"
    if not consent.get("can_respond", False) and consent.get("consent_state") != "verified":
        # unknown consent is allowed to receive/observe but not to be sent to
        # without at least an approved first-contact decision
        if action != "first_outbound_contact":
            return False, "BLOCKED_BY_CONSENT"

    if tier == "approval":
        if not approval_record or approval_record.get("authority_state") != "approved":
            return False, "BLOCKED_BY_AUTHORITY"
        if approval_record.get("action") != action:
            return False, "BLOCKED_BY_AUTHORITY"

    return True, None
