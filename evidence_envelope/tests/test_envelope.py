"""Tests for the mission-and-evidence envelope substrate.

Covers the original bounded lifecycle contract (FW-MISSION-EVIDENCE-ENVELOPE-001)
plus the corrective hardening from FW-REPAIR-EVIDENCE-ENVELOPE-001:
external, fail-closed promotion-authority verification (no name-based
heuristics), canonical mission-id validation, and durable/locked writes.

Each EnvelopeStore is rooted in a pytest tmp_path, so nothing here ever
touches a real repository file -- including the two operational ledgers
(capabilities/history.jsonl, router/decisions.jsonl), which the last
"original contract" test in this file explicitly checks remain
byte-for-byte unchanged.
"""
import dataclasses
import fcntl
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import envelope  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only locking (fcntl.flock)")


@pytest.fixture
def store(tmp_path):
    return envelope.EnvelopeStore(tmp_path / "envelope_store")


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def _gold_mission(store, tmp_path, mission_id):
    artifact = _write(tmp_path / f"{mission_id}-artifact.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store.structure_silver(mission_id, {})
    return store.validate_gold(
        mission_id,
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )


class NonProductionTestAuthorityVerifier(envelope.AuthorityVerifier):
    """TEST-ONLY stand-in for a real external authority-verification
    service. This does not authenticate anyone -- it exists solely so
    this suite can exercise EnvelopeStore's fail-closed promotion-
    authority logic without a real identity provider. Never use this
    outside tests.
    """

    def __init__(self, response=None):
        self._response = response

    def verify(self, request):
        if callable(self._response):
            return self._response(request)
        return self._response


def _valid_authority(mission_id, principal_id="qa-approver-01", attestation="test-attestation-ref-0001"):
    return envelope.VerifiedAuthority(
        principal_id=principal_id,
        authority_scope=(f"promote:{mission_id}",),
        verification_method="test-harness-non-production",
        verified_at=envelope._now(),
        attestation_reference=attestation,
    )


# =====================================================================
# Original lifecycle / hash-integrity contract (preserved, minimum tests 1-10
# from FW-MISSION-EVIDENCE-ENVELOPE-001, unchanged in intent and behavior)
# =====================================================================

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


# =====================================================================
# REPAIR A: external, fail-closed promotion-authority verification
# =====================================================================

# 1. No verifier means promotion recording is rejected.
def test_no_verifier_rejects_promotion(store, tmp_path):
    _gold_mission(store, tmp_path, "AUTH-1")
    with pytest.raises(envelope.AuthorityVerifierRequiredError):
        store.record_promotion_authority("AUTH-1", statement="please promote")
    assert store.get("AUTH-1")["promotion_status"] == envelope.NOT_PROMOTED


# 2. An actor named "James" without verification is rejected.
def test_unverified_named_actor_is_rejected(store, tmp_path):
    _gold_mission(store, tmp_path, "AUTH-2")
    # No verifier is configured. Naming "James" in the statement carries
    # no authority whatsoever -- it is never inspected as an identity.
    with pytest.raises(envelope.AuthorityVerifierRequiredError):
        store.record_promotion_authority("AUTH-2", statement="Approved by James")
    assert store.get("AUTH-2")["promotion_status"] == envelope.NOT_PROMOTED


# 3. Mixed-case and Unicode machine-like names cannot bypass verification
#    (because there is no name-based check left to bypass).
def test_no_name_based_authority_heuristic_exists():
    assert not hasattr(envelope, "_DISALLOWED_AUTHORITY_ACTORS")


@pytest.mark.parametrize(
    "suffix,principal_id",
    [
        ("a", "ClaudeBot"),
        ("b", "MODEL-v2"),
        ("c", "\u0430gent"),  # Cyrillic а (U+0430) -- looks like "agent"
        ("d", "AUTOMATION-1"),
        ("e", "James"),
    ],
)
def test_verification_outcome_is_independent_of_principal_name_shape(store, tmp_path, suffix, principal_id):
    mission_id = f"AUTH-3-{suffix}"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id, principal_id)),
    )
    record = verifier_store.record_promotion_authority(mission_id, statement="structurally verified")
    assert record["promotion_status"] == envelope.PROMOTED
    assert record["promotion_authority"]["principal_id"] == principal_id


# 4. A verified principal with the wrong scope is rejected.
def test_wrong_scope_is_rejected(store, tmp_path):
    mission_id = "AUTH-4"
    _gold_mission(store, tmp_path, mission_id)
    bad_authority = envelope.VerifiedAuthority(
        principal_id="qa-approver-01",
        authority_scope=("read:missions",),  # not a promotion scope at all
        verification_method="test-harness-non-production",
        verified_at=envelope._now(),
        attestation_reference="test-attestation-ref-0002",
    )
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(bad_authority)
    )
    with pytest.raises(envelope.AuthorityScopeError):
        verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert store.get(mission_id)["promotion_status"] == envelope.NOT_PROMOTED


# 5. A verifier result for another mission is rejected.
def test_scope_for_another_mission_is_rejected(store, tmp_path):
    mission_id = "AUTH-5"
    _gold_mission(store, tmp_path, mission_id)
    wrong_mission_authority = envelope.VerifiedAuthority(
        principal_id="qa-approver-01",
        authority_scope=("promote:AUTH-5-DIFFERENT-MISSION",),
        verification_method="test-harness-non-production",
        verified_at=envelope._now(),
        attestation_reference="test-attestation-ref-0003",
    )
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(wrong_mission_authority)
    )
    with pytest.raises(envelope.AuthorityScopeError):
        verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert store.get(mission_id)["promotion_status"] == envelope.NOT_PROMOTED


# 6. Missing attestation_reference is rejected.
def test_missing_attestation_reference_is_rejected(store, tmp_path):
    mission_id = "AUTH-6"
    _gold_mission(store, tmp_path, mission_id)
    no_attestation = envelope.VerifiedAuthority(
        principal_id="qa-approver-01",
        authority_scope=(f"promote:{mission_id}",),
        verification_method="test-harness-non-production",
        verified_at=envelope._now(),
        attestation_reference="",
    )
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(no_attestation)
    )
    with pytest.raises(envelope.MissingAttestationError):
        verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert store.get(mission_id)["promotion_status"] == envelope.NOT_PROMOTED


# 7. A valid test attestation with correct mission and scope is accepted.
def test_valid_attestation_with_correct_mission_and_scope_is_accepted(store, tmp_path):
    mission_id = "AUTH-7"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id)),
    )
    record = verifier_store.record_promotion_authority(mission_id, statement="approved for release")
    assert record["promotion_status"] == envelope.PROMOTED
    assert record["promotion_authority"]["attestation_reference"] == "test-attestation-ref-0001"


# 8. Stored evidence describes the verification method without storing secrets.
def test_stored_promotion_evidence_has_no_secret_shaped_fields(store, tmp_path):
    mission_id = "AUTH-8"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id)),
    )
    record = verifier_store.record_promotion_authority(mission_id, statement="approved for release")
    authority = record["promotion_authority"]

    assert authority["verification_method"] == "test-harness-non-production"
    forbidden = {"token", "secret", "password", "credential", "api_key", "apikey"}
    assert forbidden.isdisjoint(k.lower() for k in authority)
    serialized = json.dumps(authority).lower()
    assert "token" not in serialized
    assert "password" not in serialized

    # VerifiedAuthority itself has no field capable of carrying a secret.
    field_names = {f.name for f in dataclasses.fields(envelope.VerifiedAuthority)}
    assert field_names == {
        "principal_id", "authority_scope", "verification_method",
        "verified_at", "attestation_reference",
    }


def test_malformed_verifier_result_is_rejected(store, tmp_path):
    mission_id = "AUTH-9"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier({"not": "a VerifiedAuthority"})
    )
    with pytest.raises(envelope.MalformedVerificationResultError):
        verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert store.get(mission_id)["promotion_status"] == envelope.NOT_PROMOTED


def test_explicit_rejection_from_verifier_is_rejected(store, tmp_path):
    mission_id = "AUTH-10"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(None)
    )
    with pytest.raises(envelope.AuthorityVerificationRejectedError):
        verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert store.get(mission_id)["promotion_status"] == envelope.NOT_PROMOTED


def test_promotion_authority_requires_gold(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("AUTH-11", "1", [str(artifact)])
    verifier_store = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority("AUTH-11")),
    )
    with pytest.raises(envelope.InvalidTransitionError):
        verifier_store.record_promotion_authority("AUTH-11", statement="approved")


# =====================================================================
# REPAIR B: mission-identifier safety
# =====================================================================

# 9. Valid mission IDs work.
@pytest.mark.parametrize("mission_id", ["M-9x", "mission.001", "abc_123", "A", "9-ok"])
def test_valid_mission_ids_work(store, tmp_path, mission_id):
    artifact = _write(tmp_path / f"artifact-{mission_id}.txt", "content")
    record = store.receive_bronze(mission_id, "1", [str(artifact)])
    assert record["lifecycle_stage"] == envelope.BRONZE_RECEIVED


# 10. Slash traversal is rejected.
def test_slash_traversal_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("a/b", "1", ["x"])


# 11. Backslash traversal is rejected.
def test_backslash_traversal_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("a\\b", "1", ["x"])


# 12. ".." is rejected.
def test_dotdot_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("a..b", "1", ["x"])


# 13. Absolute paths are rejected.
def test_absolute_path_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("/etc/passwd", "1", ["x"])


# 14. Windows drive paths are rejected.
def test_windows_drive_path_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("C:\\evil", "1", ["x"])
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("C:/evil", "1", ["x"])


# 15. Control characters are rejected.
def test_control_characters_are_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("abc\x00def", "1", ["x"])
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("abc\ndef", "1", ["x"])


# 16. Unicode confusable identifiers are rejected.
def test_unicode_confusable_identifiers_are_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("miss\u0430ion", "1", ["x"])  # Cyrillic а
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("e\u0301lite", "1", ["x"])  # combining accent, NFC-unstable


# 17. Overlength identifiers are rejected.
def test_overlength_identifiers_are_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("M" * 200, "1", ["x"])


# 18. No operation escapes the store root.
def test_no_operation_escapes_the_store_root(store, tmp_path):
    hostile_ids = [
        "../escape", "..\\escape", "/abs/escape", "a/b", "a\\b",
        "C:\\evil", "a..b", "abc\x00def", "", " padded ", "M" * 200,
    ]
    ops = (
        lambda hid: store.receive_bronze(hid, "1", ["x"]),
        lambda hid: store.get(hid),
        lambda hid: store.reconstruct(hid),
        lambda hid: store.quarantine(hid, "1", reason="probe"),
        lambda hid: store.structure_silver(hid, {}),
        lambda hid: store.validate_gold(hid, [], []),
        lambda hid: store.reject(hid, "probe"),
        lambda hid: store.record_promotion_authority(hid, "probe"),
    )

    before = {p for p in tmp_path.rglob("*") if store.root not in p.parents and p != store.root}
    for hostile_id in hostile_ids:
        for op in ops:
            with pytest.raises(envelope.InvalidMissionIdError):
                op(hostile_id)
    after = {p for p in tmp_path.rglob("*") if store.root not in p.parents and p != store.root}
    assert after == before


def test_resolved_path_containment_is_enforced_directly(store):
    # Defense-in-depth: the internal path builders themselves refuse to
    # hand back anything outside store.root, independent of the regex.
    assert store._record_path("safe-id").is_relative_to(store.root.resolve())
    assert store._ledger_path("safe-id").is_relative_to(store.root.resolve())


# =====================================================================
# REPAIR C: durable snapshot writes and cross-process writer coordination
# =====================================================================

# 19. Snapshot replacement is atomic.
def test_snapshot_replacement_is_atomic(store, tmp_path):
    artifact = _write(tmp_path / "art19.txt", "content")
    store.receive_bronze("DUR-19", "1", [str(artifact)])
    for i in range(20):
        store.quarantine("DUR-19-noop", "1", reason=f"probe-{i}")
    store.structure_silver("DUR-19", {"cognitive_roles_required": ["r"]})

    leftovers = list(store.records_dir.glob(".*tmp*"))
    assert leftovers == []
    record = store.get("DUR-19")
    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED


# 20. A simulated interrupted snapshot write does not corrupt the last valid snapshot.
def test_interrupted_snapshot_write_does_not_corrupt_last_valid_snapshot(store, tmp_path, monkeypatch):
    artifact = _write(tmp_path / "art20.txt", "content")
    store.receive_bronze("DUR-20", "1", [str(artifact)])
    good_record = store.get("DUR-20")

    real_fsync = os.fsync
    call_count = {"n": 0}

    def flaky_fsync(fd):
        call_count["n"] += 1
        if call_count["n"] == 2:  # 1st call = ledger append fsync; 2nd = snapshot temp-file fsync
            raise OSError("simulated crash during snapshot fsync")
        return real_fsync(fd)

    monkeypatch.setattr(envelope.os, "fsync", flaky_fsync)
    try:
        with pytest.raises(OSError):
            store.structure_silver("DUR-20", {"cognitive_roles_required": ["r"]})
    finally:
        monkeypatch.setattr(envelope.os, "fsync", real_fsync)

    reloaded = store.get("DUR-20")
    assert reloaded == good_record
    assert reloaded["lifecycle_stage"] == envelope.BRONZE_RECEIVED
    leftovers = list(store.records_dir.glob(".*tmp*"))
    assert leftovers == []


def _mp_worker_append_quarantines(root, mission_id, worker_id, count):
    s = envelope.EnvelopeStore(root)
    for i in range(count):
        s.quarantine(mission_id, "1", reason=f"probe-from-{worker_id}-{i}")


# 21. Two concurrent process writers cannot interleave ledger records.
@POSIX_ONLY
def test_concurrent_process_writers_do_not_interleave_ledger_records(tmp_path):
    root = tmp_path / "mp_store"
    store = envelope.EnvelopeStore(root)
    mission_id = "DUR-21"
    per_worker = 15
    workers = 3

    ctx = multiprocessing.get_context("fork")
    procs = [
        ctx.Process(target=_mp_worker_append_quarantines, args=(root, mission_id, w, per_worker))
        for w in range(workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs)

    events = store._read_ledger(mission_id)  # raises LedgerIntegrityError on any tear/interleave
    assert len(events) == workers * per_worker
    reasons = {e["detail"]["reason"] for e in events}
    assert len(reasons) == workers * per_worker  # all distinct: none lost, none merged


# 22. Lock timeout fails explicitly.
@POSIX_ONLY
def test_lock_timeout_fails_explicitly(tmp_path):
    store = envelope.EnvelopeStore(tmp_path / "lock_store", lock_timeout_seconds=0.2)
    mission_id = "DUR-22"
    lock_path = store._lock_path(mission_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # An independent open file description on the same lock file, held
    # exclusively -- flock locks are per open-file-description, so this
    # reliably simulates another writer holding the lock without needing
    # a genuinely separate OS process.
    external_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(external_fd, fcntl.LOCK_EX)
    try:
        start = time.monotonic()
        with pytest.raises(envelope.LockTimeoutError):
            store.quarantine(mission_id, "1", reason="should time out")
        assert time.monotonic() - start < 5.0  # bounded, not a hang
    finally:
        fcntl.flock(external_fd, fcntl.LOCK_UN)
        os.close(external_fd)


# 23. A partial ledger line causes an integrity error.
def test_partial_ledger_line_causes_integrity_error(store, tmp_path):
    artifact = _write(tmp_path / "art23.txt", "content")
    store.receive_bronze("DUR-23", "1", [str(artifact)])
    ledger_path = store._ledger_path("DUR-23")
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write('{"transition": "SILVER_STRUCTURED", "event_key"')  # no closing brace, no newline

    with pytest.raises(envelope.LedgerIntegrityError):
        store.reconstruct("DUR-23")
    with pytest.raises(envelope.LedgerIntegrityError):
        store._read_ledger("DUR-23")


# 24. Reconstruction remains byte-equivalent to the valid live record.
def test_reconstruction_matches_live_record_through_full_lifecycle_including_promotion(store, tmp_path):
    mission_id = "DUR-24"
    artifact = _write(tmp_path / "art24.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store.structure_silver(mission_id, {"cognitive_roles_required": ["researcher"]})
    store.validate_gold(
        mission_id,
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id))
    )
    live = verifier_store.record_promotion_authority(mission_id, statement="approved")

    reconstructed = store.reconstruct(mission_id)

    assert reconstructed == live
    assert reconstructed["promotion_status"] == envelope.PROMOTED
    assert len(reconstructed["execution_events"]) == 4


def test_corrupted_snapshot_raises_integrity_error(store, tmp_path):
    artifact = _write(tmp_path / "art-corrupt.txt", "content")
    store.receive_bronze("DUR-CORRUPT", "1", [str(artifact)])
    record_path = store._record_path("DUR-CORRUPT")
    record_path.write_text("{not valid json")

    with pytest.raises(envelope.SnapshotIntegrityError):
        store.get("DUR-CORRUPT")


# 25. All previous lifecycle and hash-integrity tests continue passing:
# see the "original lifecycle / hash-integrity contract" section above --
# every one of those 11 functions is preserved verbatim in this same file
# and is collected and run alongside the tests in this section.
