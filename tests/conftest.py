import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

import governance.audit as audit_mod  # noqa: E402
import governance.approval as approval_mod  # noqa: E402
import governance.authority as authority_mod  # noqa: E402
import governance.evidence as evidence_mod  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_governance_storage(tmp_path, monkeypatch):
    """Every test gets its own audit/approval/evidence/revocation files so
    tests never read or write the real repository-tracked governance
    state, and tests never see each other's writes.

    This works because every governance.* store function resolves its
    `path` parameter dynamically at call time (``path = path or
    DEFAULT_X_PATH``) rather than baking the default in at import time --
    see the docstring note in governance/audit.py -- so monkeypatching the
    module-level constant here is actually honored on every call made
    during the test, including calls made indirectly through
    governance.pipeline.
    """
    monkeypatch.setattr(audit_mod, "DEFAULT_AUDIT_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(approval_mod, "DEFAULT_APPROVALS_PATH", tmp_path / "approvals.jsonl")
    monkeypatch.setattr(evidence_mod, "DEFAULT_EVIDENCE_PATH", tmp_path / "evidence_log.jsonl")
    monkeypatch.setattr(authority_mod, "DEFAULT_REVOCATIONS_PATH", tmp_path / "revocations.json")
    # Policy defaults are intentionally NOT redirected -- tests should
    # exercise the real, shipped policy fixtures unless a test explicitly
    # overrides `policies=` itself, so that "does the real policy table
    # behave correctly" is what gets tested by default.
    yield tmp_path
