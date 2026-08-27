"""Tests for the mission-and-evidence envelope substrate.

Covers the original bounded lifecycle contract (FW-MISSION-EVIDENCE-ENVELOPE-001),
the first corrective hardening (FW-REPAIR-EVIDENCE-ENVELOPE-001: external
fail-closed promotion-authority verification, canonical mission-id
validation, durable/locked writes), and the commit-protocol correction
(FW-REPAIR-EVIDENCE-COMMIT-PROTOCOL-002: the ledger is authoritative, the
snapshot is a derived, self-healing projection, and promotion-authority
attestations are append-only).

Each EnvelopeStore is rooted in a pytest tmp_path, so nothing here ever
touches a real repository file -- including the two operational ledgers
(capabilities/history.jsonl, router/decisions.jsonl), which the
"original contract" ledger-integrity test in this file explicitly checks
remain byte-for-byte unchanged.
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


class _FaultInjector:
    """TEST-ONLY internal seam. Raises exactly once, when EnvelopeStore._commit
    reaches `trigger_point`, then goes quiet -- this is how the commit-
    protocol tests below deterministically simulate a crash at an exact
    boundary (before the ledger is replaced / after the ledger is
    replaced but before the snapshot is / after both), per the
    instruction to use a controlled internal test seam rather than
    timing-dependent sleeps or unreliable process termination.
    """

    def __init__(self, trigger_point):
        self.trigger_point = trigger_point
        self.fired = False

    def __call__(self, point):
        if point == self.trigger_point and not self.fired:
            self.fired = True
            raise RuntimeError(f"injected failure at {point}")


def _mutate_snapshot_metadata(store, mission_id, **overrides):
    path = store._record_path(mission_id)
    wrapper = json.loads(path.read_text())
    wrapper["projection_metadata"].update(overrides)
    path.write_text(json.dumps(wrapper))


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


# 8. Repeated identical transitions do not create duplicate events. (also
# covers required test "16. Identical event-ID replay is idempotent.")
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
# External, fail-closed promotion-authority verification
# (FW-REPAIR-EVIDENCE-ENVELOPE-001, adjusted for Phase 7 of
# FW-REPAIR-EVIDENCE-COMMIT-PROTOCOL-002: recording a verified
# attestation no longer itself flips promotion_status.)
# =====================================================================

def test_no_verifier_rejects_promotion(store, tmp_path):
    _gold_mission(store, tmp_path, "AUTH-1")
    with pytest.raises(envelope.AuthorityVerifierRequiredError):
        store.record_promotion_authority("AUTH-1", statement="please promote")
    assert store.get("AUTH-1")["promotion_status"] == envelope.NOT_PROMOTED


def test_unverified_named_actor_is_rejected(store, tmp_path):
    _gold_mission(store, tmp_path, "AUTH-2")
    # No verifier is configured. Naming "James" in the statement carries
    # no authority whatsoever -- it is never inspected as an identity.
    with pytest.raises(envelope.AuthorityVerifierRequiredError):
        store.record_promotion_authority("AUTH-2", statement="Approved by James")
    assert store.get("AUTH-2")["promotion_status"] == envelope.NOT_PROMOTED


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
    assert record["promotion_authority"]["principal_id"] == principal_id
    assert record["promotion_status"] == envelope.NOT_PROMOTED  # recording != promoting


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
    assert store.get(mission_id)["promotion_authority"] is None


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
    assert store.get(mission_id)["promotion_authority"] is None


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
    assert store.get(mission_id)["promotion_authority"] is None


def test_valid_attestation_with_correct_mission_and_scope_is_accepted(store, tmp_path):
    mission_id = "AUTH-7"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id)),
    )
    record = verifier_store.record_promotion_authority(mission_id, statement="approved for release")
    assert record["promotion_authority"]["attestation_reference"] == "test-attestation-ref-0001"
    assert record["promotion_status"] == envelope.NOT_PROMOTED


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
    assert store.get(mission_id)["promotion_authority"] is None


def test_explicit_rejection_from_verifier_is_rejected(store, tmp_path):
    mission_id = "AUTH-10"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(None)
    )
    with pytest.raises(envelope.AuthorityVerificationRejectedError):
        verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert store.get(mission_id)["promotion_authority"] is None


def test_promotion_authority_requires_gold(store, tmp_path):
    artifact = _write(tmp_path / "artifact.txt", "content")
    store.receive_bronze("AUTH-11", "1", [str(artifact)])
    verifier_store = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority("AUTH-11")),
    )
    with pytest.raises(envelope.InvalidTransitionError):
        verifier_store.record_promotion_authority("AUTH-11", statement="approved")


# --- Phase 7: promotion-authority immutability -----------------------

# 18. Exact promotion-attestation replay is idempotent.
def test_exact_promotion_attestation_replay_is_idempotent(store, tmp_path):
    mission_id = "PROMO-18"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id))
    )
    first = verifier_store.record_promotion_authority(mission_id, statement="approved")
    second = verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert first == second
    events = store._read_ledger(mission_id)
    assert sum(1 for e in events if e["transition"] == "PROMOTION_AUTHORITY_RECORDED") == 1


# 17 & 19. Same event identifier with different content -> IDEMPOTENCY_CONFLICT
# / AUTHORITY_CONFLICT.
def test_different_promotion_attestation_returns_authority_conflict(store, tmp_path):
    mission_id = "PROMO-19"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store_a = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(
            _valid_authority(mission_id, principal_id="alice", attestation="ref-alice")
        ),
    )
    verifier_store_a.record_promotion_authority(mission_id, statement="approved by alice")

    verifier_store_b = envelope.EnvelopeStore(
        store.root,
        authority_verifier=NonProductionTestAuthorityVerifier(
            _valid_authority(mission_id, principal_id="bob", attestation="ref-bob")
        ),
    )
    with pytest.raises(envelope.AuthorityConflictError):
        verifier_store_b.record_promotion_authority(mission_id, statement="approved by bob")
    # AuthorityConflictError IS a general ledger-based idempotency conflict.
    with pytest.raises(envelope.IdempotencyConflictError):
        verifier_store_b.record_promotion_authority(mission_id, statement="approved by bob")

    record = store.get(mission_id)
    assert record["promotion_authority"]["principal_id"] == "alice"  # untouched, append-only held


# 20. Promotion status remains unchanged after authority recording.
def test_promotion_status_remains_unchanged_after_authority_recording(store, tmp_path):
    mission_id = "PROMO-20"
    _gold_mission(store, tmp_path, mission_id)
    verifier_store = envelope.EnvelopeStore(
        store.root, authority_verifier=NonProductionTestAuthorityVerifier(_valid_authority(mission_id))
    )
    record = verifier_store.record_promotion_authority(mission_id, statement="approved")
    assert record["promotion_status"] == envelope.NOT_PROMOTED
    assert record["promotion_authority"] is not None


# =====================================================================
# Mission-identifier safety (FW-REPAIR-EVIDENCE-ENVELOPE-001, unchanged)
# =====================================================================

@pytest.mark.parametrize("mission_id", ["M-9x", "mission.001", "abc_123", "A", "9-ok"])
def test_valid_mission_ids_work(store, tmp_path, mission_id):
    artifact = _write(tmp_path / f"artifact-{mission_id}.txt", "content")
    record = store.receive_bronze(mission_id, "1", [str(artifact)])
    assert record["lifecycle_stage"] == envelope.BRONZE_RECEIVED


def test_slash_traversal_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("a/b", "1", ["x"])


def test_backslash_traversal_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("a\\b", "1", ["x"])


def test_dotdot_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("a..b", "1", ["x"])


def test_absolute_path_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("/etc/passwd", "1", ["x"])


def test_windows_drive_path_is_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("C:\\evil", "1", ["x"])
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("C:/evil", "1", ["x"])


def test_control_characters_are_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("abc\x00def", "1", ["x"])
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("abc\ndef", "1", ["x"])


def test_unicode_confusable_identifiers_are_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("miss\u0430ion", "1", ["x"])  # Cyrillic а
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("e\u0301lite", "1", ["x"])  # combining accent, NFC-unstable


def test_overlength_identifiers_are_rejected(store):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.receive_bronze("M" * 200, "1", ["x"])


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
    assert store._record_path("safe-id").is_relative_to(store.root.resolve())
    assert store._ledger_path("safe-id").is_relative_to(store.root.resolve())


# =====================================================================
# Commit protocol: the ledger is authoritative, the snapshot is a
# derived, self-healing projection (FW-REPAIR-EVIDENCE-COMMIT-PROTOCOL-002)
# =====================================================================

def test_snapshot_replacement_is_atomic(store, tmp_path):
    artifact = _write(tmp_path / "art19.txt", "content")
    store.receive_bronze("DUR-19", "1", [str(artifact)])
    for i in range(20):
        store.quarantine("DUR-19-noop", "1", reason=f"probe-{i}")
    store.structure_silver("DUR-19", {"cognitive_roles_required": ["r"]})

    assert list(store.records_dir.glob(".*tmp*")) == []
    assert list(store.ledger_dir.glob(".*tmp*")) == []
    record = store.get("DUR-19")
    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED


# 1. Failure before ledger replace leaves ledger and snapshot unchanged.
def test_failure_before_ledger_replace_leaves_ledger_and_snapshot_unchanged(store, tmp_path):
    mission_id = "FLT-1"
    artifact = _write(tmp_path / "flt1.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    ledger_before = store._ledger_path(mission_id).read_bytes()
    snapshot_before = store._record_path(mission_id).read_bytes()

    faulty_store = envelope.EnvelopeStore(store.root, _fault_hook=_FaultInjector("before_ledger_replace"))
    with pytest.raises(RuntimeError, match="injected failure"):
        faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    assert store._ledger_path(mission_id).read_bytes() == ledger_before
    assert store._record_path(mission_id).read_bytes() == snapshot_before
    assert store.get(mission_id)["lifecycle_stage"] == envelope.BRONZE_RECEIVED


# 2. Retry after pre-commit failure records exactly one event.
def test_retry_after_pre_commit_failure_records_exactly_one_event(store, tmp_path):
    mission_id = "FLT-2"
    artifact = _write(tmp_path / "flt2.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])

    faulty_store = envelope.EnvelopeStore(store.root, _fault_hook=_FaultInjector("before_ledger_replace"))
    with pytest.raises(RuntimeError):
        faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    record = faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})
    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED
    events = store._read_ledger(mission_id)
    assert len(events) == 2  # BRONZE + exactly one SILVER, no duplicate


# 3. Failure after ledger replace but before snapshot replace leaves a
#    committed event with a stale snapshot.
def test_failure_after_ledger_replace_before_snapshot_leaves_committed_event_with_stale_snapshot(store, tmp_path):
    mission_id = "FLT-3"
    artifact = _write(tmp_path / "flt3.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    snapshot_before = store._record_path(mission_id).read_bytes()

    faulty_store = envelope.EnvelopeStore(
        store.root, _fault_hook=_FaultInjector("after_ledger_replace_before_snapshot")
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    events = store._read_ledger(mission_id)
    assert len(events) == 2
    assert events[-1]["transition"] == "SILVER_STRUCTURED"
    assert store._record_path(mission_id).read_bytes() == snapshot_before  # still stale


# 4. Reload after that failure reconstructs the committed state from the ledger.
def test_reload_after_post_ledger_failure_reconstructs_committed_state(store, tmp_path):
    mission_id = "FLT-4"
    artifact = _write(tmp_path / "flt4.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])

    faulty_store = envelope.EnvelopeStore(
        store.root, _fault_hook=_FaultInjector("after_ledger_replace_before_snapshot")
    )
    with pytest.raises(RuntimeError):
        faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    reloaded = store.get(mission_id)
    assert reloaded["lifecycle_stage"] == envelope.SILVER_STRUCTURED
    assert store.reconstruct(mission_id) == reloaded


# 5. Reload repairs the stale snapshot atomically.
def test_reload_repairs_the_stale_snapshot_on_disk(store, tmp_path):
    mission_id = "FLT-5"
    artifact = _write(tmp_path / "flt5.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])

    faulty_store = envelope.EnvelopeStore(
        store.root, _fault_hook=_FaultInjector("after_ledger_replace_before_snapshot")
    )
    with pytest.raises(RuntimeError):
        faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    store.get(mission_id)  # triggers the repair as a side effect

    wrapper = json.loads(store._record_path(mission_id).read_text())
    events = store._read_ledger(mission_id)
    assert wrapper["record"]["lifecycle_stage"] == envelope.SILVER_STRUCTURED
    assert wrapper["projection_metadata"]["event_count"] == len(events)
    assert wrapper["projection_metadata"]["last_event_id"] == events[-1]["event_id"]
    assert wrapper["projection_metadata"]["ledger_content_hash"] == envelope._ledger_content_hash(events)


# 6. Retry after that failure does not duplicate the committed event.
def test_retry_after_post_ledger_failure_does_not_duplicate_event(store, tmp_path):
    mission_id = "FLT-6"
    artifact = _write(tmp_path / "flt6.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])

    faulty_store = envelope.EnvelopeStore(
        store.root, _fault_hook=_FaultInjector("after_ledger_replace_before_snapshot")
    )
    with pytest.raises(RuntimeError):
        faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    record = faulty_store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})
    events = store._read_ledger(mission_id)
    assert len(events) == 2
    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED


# 7. Snapshot deletion does not lose state.
def test_snapshot_deletion_does_not_lose_state(store, tmp_path):
    mission_id = "FLT-7"
    artifact = _write(tmp_path / "flt7.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})

    store._record_path(mission_id).unlink()
    record = store.get(mission_id)
    assert record["lifecycle_stage"] == envelope.SILVER_STRUCTURED
    assert store._record_path(mission_id).exists()  # self-healed


# 8. Snapshot corruption does not override valid ledger history.
def test_snapshot_corruption_does_not_override_valid_ledger_history(store, tmp_path):
    mission_id = "FLT-8"
    artifact = _write(tmp_path / "flt8.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store._record_path(mission_id).write_text(
        '{"record": {"lifecycle_stage": "GOLD_VALIDATED"}, "not": valid json'
    )

    record = store.get(mission_id)
    assert record["lifecycle_stage"] == envelope.BRONZE_RECEIVED  # ledger truth, not the forged snapshot


# 9. Snapshot with wrong last_event_id is detected and rebuilt.
def test_snapshot_with_wrong_last_event_id_is_detected_and_rebuilt(store, tmp_path):
    mission_id = "FLT-9"
    artifact = _write(tmp_path / "flt9.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    _mutate_snapshot_metadata(store, mission_id, last_event_id="forged-event-id")

    store.get(mission_id)
    events = store._read_ledger(mission_id)
    wrapper = json.loads(store._record_path(mission_id).read_text())
    assert wrapper["projection_metadata"]["last_event_id"] == events[-1]["event_id"]


# 10. Snapshot with wrong event_count is detected and rebuilt.
def test_snapshot_with_wrong_event_count_is_detected_and_rebuilt(store, tmp_path):
    mission_id = "FLT-10"
    artifact = _write(tmp_path / "flt10.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    _mutate_snapshot_metadata(store, mission_id, event_count=999)

    store.get(mission_id)
    events = store._read_ledger(mission_id)
    wrapper = json.loads(store._record_path(mission_id).read_text())
    assert wrapper["projection_metadata"]["event_count"] == len(events)


# 11. Snapshot with wrong ledger hash is detected and rebuilt.
def test_snapshot_with_wrong_ledger_hash_is_detected_and_rebuilt(store, tmp_path):
    mission_id = "FLT-11"
    artifact = _write(tmp_path / "flt11.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    _mutate_snapshot_metadata(store, mission_id, ledger_content_hash="0" * 64)

    store.get(mission_id)
    events = store._read_ledger(mission_id)
    wrapper = json.loads(store._record_path(mission_id).read_text())
    assert wrapper["projection_metadata"]["ledger_content_hash"] == envelope._ledger_content_hash(events)


# 12. Partial final ledger record raises LEDGER_INTEGRITY_ERROR.
def test_partial_final_ledger_record_raises_integrity_error(store, tmp_path):
    mission_id = "FLT-12"
    artifact = _write(tmp_path / "flt12.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    ledger_path = store._ledger_path(mission_id)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write('{"transition": "SILVER_STRUCTURED", "event_key"')  # no closing brace, no newline

    with pytest.raises(envelope.LedgerIntegrityError):
        store.reconstruct(mission_id)
    with pytest.raises(envelope.LedgerIntegrityError):
        store.get(mission_id)


# 13. Corrupted middle ledger record raises LEDGER_INTEGRITY_ERROR.
def test_corrupted_middle_ledger_record_raises_integrity_error(store, tmp_path):
    mission_id = "FLT-13"
    artifact = _write(tmp_path / "flt13.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})
    store.validate_gold(
        mission_id,
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )
    ledger_path = store._ledger_path(mission_id)
    lines = ledger_path.read_text().splitlines(keepends=True)
    assert len(lines) == 3
    lines[1] = "{not valid json at all}\n"
    ledger_path.write_text("".join(lines))

    with pytest.raises(envelope.LedgerIntegrityError):
        store.reconstruct(mission_id)


# 14. No transition proceeds after ledger-integrity failure.
def test_no_transition_proceeds_after_ledger_integrity_failure(store, tmp_path):
    mission_id = "FLT-14"
    artifact = _write(tmp_path / "flt14.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    ledger_path = store._ledger_path(mission_id)
    ledger_path.write_text('{"transition": "BRONZE_RECEIVED"')  # corrupt: no closing, no newline

    with pytest.raises(envelope.LedgerIntegrityError):
        store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})
    assert ledger_path.read_text() == '{"transition": "BRONZE_RECEIVED"'  # untouched, not "fixed up"

    # The lock was released properly (not left stuck): an unrelated
    # mission works fine right after.
    other_artifact = _write(tmp_path / "flt14b.txt", "content")
    other = store.receive_bronze("FLT-14B", "1", [str(other_artifact)])
    assert other["lifecycle_stage"] == envelope.BRONZE_RECEIVED


def _mp_worker_append_quarantines(root, mission_id, worker_id, count):
    s = envelope.EnvelopeStore(root)
    for i in range(count):
        s.quarantine(mission_id, "1", reason=f"probe-from-{worker_id}-{i}")


# 15. Concurrent writers remain serialized.
@POSIX_ONLY
def test_concurrent_process_writers_remain_serialized(tmp_path):
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


@POSIX_ONLY
def test_lock_timeout_fails_explicitly(tmp_path):
    store = envelope.EnvelopeStore(tmp_path / "lock_store", lock_timeout_seconds=0.2)
    mission_id = "DUR-22"
    lock_path = store._lock_path(mission_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

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


# 21. Historical event order and contents remain unchanged.
def test_historical_event_order_and_contents_remain_unchanged(store, tmp_path):
    mission_id = "FLT-21"
    artifact = _write(tmp_path / "flt21.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})
    before = store._read_ledger(mission_id)

    store.validate_gold(
        mission_id,
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )
    after = store._read_ledger(mission_id)

    assert after[: len(before)] == before
    assert len(after) == len(before) + 1


# 22. Reconstruction remains deterministic and equivalent across fresh store instances.
def test_reconstruction_is_deterministic_across_fresh_store_instances(store, tmp_path):
    mission_id = "FLT-22"
    artifact = _write(tmp_path / "flt22.txt", "content")
    store.receive_bronze(mission_id, "1", [str(artifact)])
    store.structure_silver(mission_id, {"cognitive_roles_required": ["r"]})
    store.validate_gold(
        mission_id,
        acceptance_tests=[{"name": "smoke_test", "passed": True}],
        evidence_artifacts=[{"type": "log", "ref": "smoke_test.log"}],
    )

    fresh_store = envelope.EnvelopeStore(store.root)
    assert fresh_store.reconstruct(mission_id) == store.reconstruct(mission_id)
    assert fresh_store.get(mission_id) == store.get(mission_id)


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
    assert reconstructed["promotion_authority"] is not None
    assert reconstructed["promotion_status"] == envelope.NOT_PROMOTED  # recording != promoting
    assert len(reconstructed["execution_events"]) == 4
