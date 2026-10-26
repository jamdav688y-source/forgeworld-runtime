"""Consent / minimal-contact-record management (mission Section 12).

Distinguishes receive/store/analyze/respond/recontact/evidence permissions
per contact. A conversation happening is not blanket permission for reuse.
"""
import time
from pathlib import Path

from . import ledger

STOP_WORDS = {"stop", "unsubscribe", "opt out", "optout", "cancel", "remove me"}


def is_stop_word(text: str) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    return normalized in STOP_WORDS


def get_consent(contact_id: str, path: Path = None) -> dict:
    path = path if path is not None else ledger.CONSENT_LEDGER
    records = ledger.find(path, contact_id=contact_id)
    if not records:
        return {
            "contact_id": contact_id,
            "consent_state": "unknown",
            "can_receive": True,
            "can_store": True,
            "can_analyze": True,
            "can_respond": True,
            "can_recontact": False,
            "can_use_as_evidence": True,
        }
    return records[-1]  # most recent entry wins; ledger is append-only history


def record_consent(
    contact_id: str,
    consent_state: str,
    source: str,
    path: Path = None,
    **overrides,
) -> dict:
    path = path if path is not None else ledger.CONSENT_LEDGER
    prior = get_consent(contact_id, path)
    record = {
        "contact_id": contact_id,
        "consent_state": consent_state,
        "source": source,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "can_receive": overrides.get("can_receive", prior["can_receive"]),
        "can_store": overrides.get("can_store", prior["can_store"]),
        "can_analyze": overrides.get("can_analyze", prior["can_analyze"]),
        "can_respond": overrides.get("can_respond", prior["can_respond"]),
        "can_recontact": overrides.get("can_recontact", prior["can_recontact"]),
        "can_use_as_evidence": overrides.get("can_use_as_evidence", prior["can_use_as_evidence"]),
    }
    ledger.append(path, record)
    return record


def apply_stop_word_if_present(contact_id: str, text: str, path: Path = None):
    """Safe, low-risk automatic action per the authority matrix: stopword -> revoke."""
    path = path if path is not None else ledger.CONSENT_LEDGER
    if is_stop_word(text):
        return record_consent(
            contact_id, "revoked", source="stopword_auto_detect", path=path,
            can_respond=False, can_recontact=False,
        )
    return None
