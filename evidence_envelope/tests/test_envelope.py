"""Tests for the mission-and-evidence envelope substrate (FW-MISSION-EVIDENCE-ENVELOPE-001).

Each EnvelopeStore is rooted in a pytest tmp_path, so nothing here ever
touches a real repository file -- including the two operational ledgers
(capabilities/history.jsonl, router/decisions.jsonl), which the last test
in this file explicitly checks remain byte-for-byte unchanged.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import envelope  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def store(tmp_path):
    return envelope.EnvelopeStore(tmp_path / "envelope_store")


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


# 1. A valid artifact enters BRONZE with its correct hash.
def test_valid_artifact_enters_bronze_with_correct_hash(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "hello forgeworld")
    expected_hash = hashlib.sha256(b"hello forgeworld").hexdigest()

    record = store.receive_bronze(
        mission_id="M-1",
        mission_version="1",
        source_artifacts=[str(artifact)],
    )

    assert record["lifecycle_stage"] == envelope.BRONZE_RECEIVED
    assert record["content_hashes"][str(artifact)] == expected_hash
    assert record["schema_version"] == envelope.SCHEMA_VERSION
    assert record["promotion_status"] == envelope.NOT_PROMOTED


# 2. Altering the artifact produces a different hash.
def test_altering_artifact_produces_different_hash(store, tmp_path):
    v1 = _write(tmp_path / "v1.txt", "original content")
    v2 = _write(tmp_path / "v2.txt", "altered content")

    r1 = store.receive_bronze("M-2a", "1", [str(v1)])
    r2 = store.receive_bronze("M-2b", "1", [str(v2)])

    assert r1["content_hashes"][str(v1)] != r2["content_hashes"][str(v2)]


# 3. A missing artifact cannot enter BRONZE.
def test_missing_artifact_cannot_enter_bronze(store, tmp_path):
    missing = tmp_path / "does_not_exist.txt"

    record = store.receive_bronze("M-3", "1", [str(missing)])

    assert record["lifecycle_stage"] == envelope.QUARANTINED
    assert record["lifecycle_stage"] != envelope.BRONZE_RECEIVED
    assert any("missing source artifact" in gap for gap in record["unresolved_gaps"])


# 4. Malformed input enters QUARANTINED.
def test_malformed_input_enters_quarantined(store):
    record = store.receive_bronze("M-4", "1", source_artifacts=None)

    assert record["lifecycle_stage"] == envelope.QUARANTINED
    assert record["unresolved_gaps"]


# 5. BRONZE can transition to SILVER with structured metadata.
def test_bronze_transitions_to_silver_with_structured_metadata(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("M-5", "1", [str(artifact)])

    record = store.structure_silver(
        "M-5",
        {
            "cognitive_roles_required": ["researcher"],
            "capabilities_required": ["python"],
            "context_budget": {"tokens": 50000},
            "privacy_tier": "internal",
            "authority_tier": "standard",
        },
    )

    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED
    assert record["cognitive_roles_required"] == ["researcher"]
    assert record["capabilities_required"] == ["python"]
    assert record["context_budget"] == {"tokens": 50000}


# 6. SILVER cannot transition to GOLD without acceptance evidence.
def test_silver_cannot_transition_to_gold_without_acceptance_evidence(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("M-6", "1", [str(artifact)])
    store.structure_silver("M-6", {"cognitive_roles_required": ["researcher"]})

    with pytest.raises(envelope.AcceptanceEvidenceMissingError):
        store.validate_gold("M-6", acceptance_tests=[], evidence_artifacts=[])

    record = store.get("M-6")
    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED


# 7. GOLD does not change promotion_status automatically.
def test_gold_does_not_change_promotion_status_automatically(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("M-7", "1", [str(artifact)])
    store.structure_silver("M-7", {})

    record = store.validate_gold(
        "M-7",
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )

    assert record["lifecycle_stage"] == envelope.GOLD_VALIDATED
    assert record["promotion_status"] == envelope.NOT_PROMOTED
    assert record["promotion_authority"] is None


# 8. Repeated identical transitions do not create duplicate events.
def test_repeated_identical_transitions_do_not_duplicate_events(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")

    r1 = store.receive_bronze("M-8", "1", [str(artifact)])
    r2 = store.receive_bronze("M-8", "1", [str(artifact)])
    assert len(r1["execution_events"]) == len(r2["execution_events"]) == 1
    assert r1["execution_events"] == r2["execution_events"]

    r3 = store.structure_silver("M-8", {"cognitive_roles_required": ["researcher"]})
    r4 = store.structure_silver("M-8", {"cognitive_roles_required": ["researcher"]})
    assert len(r3["execution_events"]) == len(r4["execution_events"]) == 2

    ledger_lines = store._read_ledger("M-8")
    assert len(ledger_lines) == 2  # one BRONZE_RECEIVED + one SILVER_STRUCTURED, no duplicates


# 9. Historical events remain reconstructible.
def test_historical_events_remain_reconstructible(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("M-9", "1", [str(artifact)])
    store.structure_silver("M-9", {"cognitive_roles_required": ["researcher"]})
    live = store.validate_gold(
        "M-9",
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )

    reconstructed = store.reconstruct("M-9")

    assert reconstructed == live
    assert reconstructed["lifecycle_stage"] == envelope.GOLD_VALIDATED
    assert len(reconstructed["execution_events"]) == 3


# 10. Existing repository tests and operational ledgers remain unchanged.
def test_existing_repository_tests_and_ledgers_remain_unchanged():
    result = subprocess.run(
        ["pytest", "capabilities/tests/", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    diff = subprocess.run(
        ["git", "diff", "--exit-code", "--", "capabilities/history.jsonl", "router/decisions.jsonl"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert diff.returncode == 0, "operational ledger(s) changed:\n" + diff.stdout


# -- Additional coverage: promotion authority separation ----------------

def test_promotion_requires_separately_recorded_human_authority(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("M-11", "1", [str(artifact)])
    store.structure_silver("M-11", {})
    store.validate_gold(
        "M-11",
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )

    with pytest.raises(envelope.SelfGrantedAuthorityError):
        store.record_promotion_authority("M-11", authorized_by="model", statement="approved")

    unpromoted = store.get("M-11")
    assert unpromoted["promotion_status"] == envelope.NOT_PROMOTED

    promoted = store.record_promotion_authority(
        "M-11", authorized_by="jane.doe@example.com", statement="Reviewed and approved for release."
    )
    assert promoted["promotion_status"] == envelope.PROMOTED
    assert promoted["promotion_authority"]["authorized_by"] == "jane.doe@example.com"


def test_failed_acceptance_evidence_routes_to_rejected(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("M-12", "1", [str(artifact)])
    store.structure_silver("M-12", {})

    record = store.validate_gold(
        "M-12",
        acceptance_tests=[{"name": "smoke_test", "passed": False}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )

    assert record["lifecycle_stage"] == envelope.REJECTED
