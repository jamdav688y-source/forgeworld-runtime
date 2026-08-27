"""Shared test harness: isolates every test in a fresh temp directory for
ledgers/config, and provides fixture-signing helpers. No test touches the
real whatsapp/ledgers/ files.
"""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path

from whatsapp.src import ledger, modes

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

TEST_APP_SECRET = "fixture-app-secret-not-real"
TEST_VERIFY_TOKEN = "fixture-verify-token-not-real"
TEST_ID_SALT = "fixture-id-salt-not-real"


def load_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def sign(raw_body: bytes, secret: str = TEST_APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class WhatsAppTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)

        self._orig_ledger_paths = {
            "CONVERSATION_LEDGER": ledger.CONVERSATION_LEDGER,
            "EXECUTION_LEDGER": ledger.EXECUTION_LEDGER,
            "CONSENT_LEDGER": ledger.CONSENT_LEDGER,
            "OPPORTUNITY_LEDGER": ledger.OPPORTUNITY_LEDGER,
            "SIGNAL_LEDGER": ledger.SIGNAL_LEDGER,
        }
        ledger.CONVERSATION_LEDGER = tmp_path / "conversation_ledger.jsonl"
        ledger.EXECUTION_LEDGER = tmp_path / "execution_ledger.jsonl"
        ledger.CONSENT_LEDGER = tmp_path / "consent_ledger.jsonl"
        ledger.OPPORTUNITY_LEDGER = tmp_path / "opportunity_ledger.jsonl"
        ledger.SIGNAL_LEDGER = tmp_path / "signal_ledger.jsonl"

        self._orig_config_path = modes.CONFIG_PATH
        modes.CONFIG_PATH = tmp_path / "config.json"
        modes.save_config({
            "schema_version": "1.0",
            "mode": {
                "inbound": "ENABLED_AFTER_VERIFICATION",
                "outbound": "DRAFT_ONLY",
                "campaign": "DISABLED",
                "autonomous_commitments": "PROHIBITED",
            },
            "authority": {"grants": []},
        })

        self._orig_env = {
            k: os.environ.get(k) for k in [
                "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_ID_SALT",
                "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
            ]
        }
        os.environ["WHATSAPP_APP_SECRET"] = TEST_APP_SECRET
        os.environ["WHATSAPP_VERIFY_TOKEN"] = TEST_VERIFY_TOKEN
        os.environ["WHATSAPP_ID_SALT"] = TEST_ID_SALT
        os.environ.pop("WHATSAPP_ACCESS_TOKEN", None)
        os.environ.pop("WHATSAPP_PHONE_NUMBER_ID", None)

    def tearDown(self):
        for k, v in self._orig_ledger_paths.items():
            setattr(ledger, k, v)
        modes.CONFIG_PATH = self._orig_config_path
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()
