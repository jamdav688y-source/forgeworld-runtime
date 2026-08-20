"""Shared test harness: isolates every test from real repository state,
exactly like perception/tests/base.py and whatsapp/tests/base.py before it.

Monkeypatches every module-level path constant this package's modules
write to, restoring originals in tearDown, so no test run ever touches:
  - whatsapp/ledgers/execution_ledger.jsonl (the real, shared Execution Ledger)
  - governance/evidence_log.jsonl (unused by this package directly, but
    isolated anyway in case a future test exercises governance.evidence)
  - router/decisions.jsonl (the real, tracked DispatchDecision ledger)
  - capabilities/history.jsonl (the real, tracked learning-record ledger --
    isolated under BOTH module-level bindings that point to it:
    router.record_outcome.HISTORY_PATH, the write path, and
    router.mission_router.HISTORY_PATH, the read path load_history() uses)
  - capability_dispatch/data/artifacts/ (the real governed artifact store)

Also proves offline safety structurally, not just by convention: setUp
replaces socket.create_connection with a function that raises, so any
test that accidentally triggers a live network probe (e.g. via
capabilities.discover.probe_all()'s "network" check type) fails loudly
instead of silently hanging or depending on network availability.
"""
import socket
import tempfile
import unittest
from pathlib import Path

from governance import evidence as gov_evidence
from router import mission_router, record_outcome
from whatsapp.src import ledger as wa_ledger

from capability_dispatch.src import ingest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIXTURES_DIR / name


def _blocked_network(*args, **kwargs):
    raise RuntimeError(
        "network access attempted during a capability_dispatch test run -- "
        "pass an explicit reachability_state fixture instead of letting "
        "capabilities.discover.probe_all() run for real"
    )


class CapabilityDispatchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)

        self._orig_execution_ledger = wa_ledger.EXECUTION_LEDGER
        wa_ledger.EXECUTION_LEDGER = tmp_path / "execution_ledger.jsonl"

        self._orig_evidence_path = gov_evidence.DEFAULT_EVIDENCE_PATH
        gov_evidence.DEFAULT_EVIDENCE_PATH = tmp_path / "evidence_log.jsonl"

        self._orig_decisions_path = mission_router.DECISIONS_PATH
        mission_router.DECISIONS_PATH = tmp_path / "decisions.jsonl"

        self._orig_record_history_path = record_outcome.HISTORY_PATH
        record_outcome.HISTORY_PATH = tmp_path / "history.jsonl"
        self._orig_router_history_path = mission_router.HISTORY_PATH
        mission_router.HISTORY_PATH = tmp_path / "history.jsonl"

        self._orig_artifact_store = ingest.ARTIFACT_STORE
        ingest.ARTIFACT_STORE = tmp_path / "artifacts"

        self._orig_create_connection = socket.create_connection
        socket.create_connection = _blocked_network

    def tearDown(self):
        wa_ledger.EXECUTION_LEDGER = self._orig_execution_ledger
        gov_evidence.DEFAULT_EVIDENCE_PATH = self._orig_evidence_path
        mission_router.DECISIONS_PATH = self._orig_decisions_path
        record_outcome.HISTORY_PATH = self._orig_record_history_path
        mission_router.HISTORY_PATH = self._orig_router_history_path
        ingest.ARTIFACT_STORE = self._orig_artifact_store
        socket.create_connection = self._orig_create_connection
        self._tmp.cleanup()

    # Deterministic reachability fixture: every registered capability
    # "reachable", with a labeled synthetic evidence string -- never a
    # real probe.
    FIXTURE_REACHABILITY = {
        cid: {"reachability_confidence": 1.0, "evidence": "fixture: assumed reachable, no real probe run"}
        for cid in (
            "claude_code", "chatgpt", "local_llm", "desktop_runtime", "python",
            "git", "github", "zapier", "gmail", "google_drive", "airtable",
        )
    }
