"""Shared test harness: isolates every test from real repository state.

Same pattern as whatsapp/tests/base.py's WhatsAppTestCase -- monkeypatch
every module-level path constant to a fresh temp directory in setUp, and
restore the originals in tearDown, so no test ever touches:
  - whatsapp/ledgers/execution_ledger.jsonl (the real, shared Execution Ledger)
  - governance/evidence_log.jsonl (the real, tracked NRM-incident evidence log)
  - perception/data/images/ (the real governed image store)
  - perception/ledgers/knowledge_vault.jsonl (the real Knowledge Vault)
"""
import tempfile
import unittest
from pathlib import Path

from governance import evidence as gov_evidence
from perception.src import ingest, promotion
from whatsapp.src import ledger as wa_ledger

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def fixture_path(name: str) -> Path:
    return FIXTURES_DIR / name


class PerceptionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)

        self._orig_execution_ledger = wa_ledger.EXECUTION_LEDGER
        wa_ledger.EXECUTION_LEDGER = tmp_path / "execution_ledger.jsonl"

        self._orig_evidence_path = gov_evidence.DEFAULT_EVIDENCE_PATH
        gov_evidence.DEFAULT_EVIDENCE_PATH = tmp_path / "evidence_log.jsonl"

        self._orig_image_store = ingest.IMAGE_STORE
        ingest.IMAGE_STORE = tmp_path / "images"

        self._orig_knowledge_vault = promotion.KNOWLEDGE_VAULT
        promotion.KNOWLEDGE_VAULT = tmp_path / "knowledge_vault.jsonl"

    def tearDown(self):
        wa_ledger.EXECUTION_LEDGER = self._orig_execution_ledger
        gov_evidence.DEFAULT_EVIDENCE_PATH = self._orig_evidence_path
        ingest.IMAGE_STORE = self._orig_image_store
        promotion.KNOWLEDGE_VAULT = self._orig_knowledge_vault
        self._tmp.cleanup()
