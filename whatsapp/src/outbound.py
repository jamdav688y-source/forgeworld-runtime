"""Outbound adapter: gated by mode, authority, consent, the 24h customer
service window, and credential presence -- in that order. Fails closed.

`http_post` is dependency-injected so tests can verify the exact request
shape without making a network call; the default implementation is a real
Meta Graph API call, used only once real credentials exist.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import authority, consent as consent_mod, ledger, modes, normalize

GRAPH_API_VERSION = "v21.0"  # verify against developers.facebook.com before go-live; see governance/01
CSW_HOURS_DEFAULT = 24


def _default_http_post(url: str, headers: dict, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _credentials() -> dict:
    return {
        "access_token": os.environ.get("WHATSAPP_ACCESS_TOKEN"),
        "phone_number_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID"),
    }


def _credentials_present(creds: dict) -> bool:
    return bool(creds.get("access_token")) and bool(creds.get("phone_number_id"))


def _last_inbound_at(conversation_id: str) -> datetime:
    events = ledger.find(ledger.CONVERSATION_LEDGER, conversation_id=conversation_id, direction="inbound")
    if not events:
        return None
    latest = max(events, key=lambda e: e["occurred_at"])
    return datetime.strptime(latest["occurred_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _csw_open(conversation_id: str, hours: int = CSW_HOURS_DEFAULT) -> bool:
    last_inbound = _last_inbound_at(conversation_id)
    if last_inbound is None:
        return False
    elapsed_hours = (datetime.now(timezone.utc) - last_inbound).total_seconds() / 3600
    return elapsed_hours <= hours


def _record_terminal(draft_id: str, event_id: str, action: str, state: str, reason: str) -> dict:
    record = {
        "draft_id": draft_id,
        "event_id": event_id,
        "action": action,
        "state": state,
        "reason": reason,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    ledger.append(ledger.EXECUTION_LEDGER, record)
    return record


def send(
    draft: dict,
    contact_id: str,
    to_phone: str,
    template_name: str = None,
    http_post=None,
    config: dict = None,
) -> dict:
    """Attempt to deliver an approved draft. Returns a terminal-state record.
    Never raises for governance blocks -- those are results, not exceptions.
    """
    http_post = http_post or _default_http_post
    config = config or modes.load_config()

    draft_id = draft["draft_id"]
    event_id = draft["event_id"]
    action = draft["action"]
    conversation_id = draft["conversation_id"]

    # Idempotency: never re-send an already-delivered draft. Without this, a
    # duplicate call (double-click, retried script, race between two callers)
    # would message the customer twice.
    if ledger.exists_by(ledger.EXECUTION_LEDGER, draft_id=draft_id, state="SAFE_AUTOMATION_EXECUTED"):
        return _record_terminal(
            draft_id, event_id, action, "VALIDATED_COMPLETE",
            "already sent; ignoring duplicate send attempt",
        )

    # Recipient binding: the phone number a caller supplies to send to must
    # be the same person the approved draft was written for. Without this
    # check, nothing stops an approved draft for one contact being delivered
    # to an arbitrary caller-supplied number.
    if normalize.hash_phone(to_phone) != contact_id:
        return _record_terminal(
            draft_id, event_id, action, "BLOCKED_BY_AUTHORITY",
            "to_phone does not match the contact_id this draft was approved for",
        )

    matches = ledger.find(ledger.EXECUTION_LEDGER, draft_id=draft_id, state="APPROVED_AWAITING_SEND")
    approval_record = matches[-1] if matches else None

    consent = consent_mod.get_consent(contact_id)

    authorized, blocker = authority.check_send_authorized(action, approval_record, consent, config)
    if not authorized:
        return _record_terminal(draft_id, event_id, action, blocker, "authority/consent/mode check failed")

    creds = _credentials()
    if not _credentials_present(creds):
        return _record_terminal(
            draft_id, event_id, action, "BLOCKED_BY_CONFIGURATION",
            "WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not configured",
        )

    csw_open = _csw_open(conversation_id)
    if not csw_open and not template_name:
        return _record_terminal(
            draft_id, event_id, action, "BLOCKED_BY_POLICY",
            "customer service window closed and no approved template supplied",
        )

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{creds['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {creds['access_token']}",
        "Content-Type": "application/json",
    }
    if csw_open and not template_name:
        body = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": draft["message"]},
        }
    else:
        body = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {"name": template_name, "language": {"code": "en_US"}},
        }

    try:
        response = http_post(url, headers, body)
    except urllib.error.URLError as e:
        return _record_terminal(draft_id, event_id, action, "REVISION_REQUIRED", f"send failed: {e}")

    record = _record_terminal(
        draft_id, event_id, action, "SAFE_AUTOMATION_EXECUTED",
        "delivered to WhatsApp Cloud API; awaiting status webhook reconciliation",
    )
    record["platform_response"] = response
    sent_messages = response.get("messages", []) if isinstance(response, dict) else []
    if sent_messages:
        record["platform_message_id"] = sent_messages[0].get("id")
        ledger.append(ledger.EXECUTION_LEDGER, {
            "draft_id": draft_id,
            "event_id": event_id,
            "platform_message_id": record["platform_message_id"],
            "state": "SAFE_AUTOMATION_EXECUTED",
            "reason": "platform_message_id linkage for reconciliation",
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    return record
