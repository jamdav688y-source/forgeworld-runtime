"""Tests for the Constitutional Court state-transition graph
(FW-CONSTITUTIONAL-COURT-STATE-GRAPH-001), built on court.py.

Every CourtStore is rooted in a pytest tmp_path, so nothing here touches a
real repository file. Mirrors evidence_envelope/tests/test_envelope.py's
conventions (fixture shape, TEST-ONLY AuthorityVerifier stand-in, valid-
authority builder) so both suites read the same way.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import court  # noqa: E402
import envelope  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return court.CourtStore(tmp_path / "court_store")


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


class NonProductionTestAuthorityVerifier(envelope.AuthorityVerifier):
    """TEST-ONLY stand-in, identical in spirit to the one in
    test_envelope.py: authenticates nobody, exists solely to exercise
    CourtStore's fail-closed adjudication-authority logic."""

    def __init__(self, response=None):
        self._response = response

    def verify(self, request):
        if callable(self._response):
            return self._response(request)
        return self._response


def _valid_authority(case_id, principal_id="justice-01", attestation="test-attestation-ref-0001"):
    return envelope.VerifiedAuthority(
        principal_id=principal_id,
        authority_scope=(f"adjudicate:{case_id}",),
        verification_method="test-harness-non-production",
        verified_at=envelope._now(),
        attestation_reference=attestation,
    )


def _filed_case(store, tmp_path, case_id, claim="the mission violated authority tier bounds"):
    artifact = _write(tmp_path / f"{case_id}-evidence.txt", "content")
    return store.file_case(case_id, "1", claim, [str(artifact)])


def _admitted_case(store, tmp_path, case_id, **kwargs):
    _filed_case(store, tmp_path, case_id, **kwargs)
    return store.rule_admissibility(case_id, [{"name": "has_claim_and_evidence", "passed": True}])


def _decided_case(store, tmp_path, case_id, ruling=court.APPROVED, verifier=None):
    _admitted_case(store, tmp_path, case_id)
    store.authority_verifier = verifier or NonProductionTestAuthorityVerifier(_valid_authority(case_id))
    return store.decide(
        case_id,
        ruling,
        decision_evidence=[{"type": "log", "ref": "hearing.log"}],
        rationale="evidence supports the ruling",
        statement="ruling on the merits",
    )


# =====================================================================
# Filing, admissibility, and the FILED -> ADMITTED/INADMISSIBLE branch
# =====================================================================

def test_valid_filing_enters_filed_with_correct_hash(store, tmp_path):
    artifact = _write(tmp_path / "evidence.txt", "hello court")
    record = store.file_case("case-001", "1", "claim text", [str(artifact)])
    assert record["case_stage"] == court.FILED
    assert record["content_hashes"][str(artifact)] == envelope.sha256_file(artifact)


def test_filing_without_claim_is_quarantined(store, tmp_path):
    artifact = _write(tmp_path / "evidence.txt", "content")
    record = store.file_case("case-002", "1", "", [str(artifact)])
    assert record["case_stage"] == court.QUARANTINED
    assert "claim is missing or empty" in record["unresolved_gaps"]


def test_filing_with_missing_artifact_is_quarantined(store, tmp_path):
    record = store.file_case("case-003", "1", "claim", [str(tmp_path / "nope.txt")])
    assert record["case_stage"] == court.QUARANTINED


def test_refiling_same_case_with_different_content_conflicts(store, tmp_path):
    _filed_case(store, tmp_path, "case-004")
    artifact2 = _write(tmp_path / "other-evidence.txt", "different")
    with pytest.raises(court.CaseConflictError):
        store.file_case("case-004", "2", "a different claim", [str(artifact2)])


def test_admissibility_ruling_passes_to_admitted(store, tmp_path):
    _filed_case(store, tmp_path, "case-005")
    record = store.rule_admissibility("case-005", [{"name": "check", "passed": True}])
    assert record["case_stage"] == court.ADMITTED


def test_admissibility_ruling_fails_to_inadmissible(store, tmp_path):
    _filed_case(store, tmp_path, "case-006")
    record = store.rule_admissibility("case-006", [{"name": "check", "passed": False}])
    assert record["case_stage"] == court.INADMISSIBLE
    assert any("check" in gap for gap in record["unresolved_gaps"])


def test_admissibility_ruling_requires_explicit_checks(store, tmp_path):
    _filed_case(store, tmp_path, "case-007")
    with pytest.raises(envelope.AcceptanceEvidenceMissingError):
        store.rule_admissibility("case-007", [])


def test_admissibility_ruling_requires_filed_stage(store, tmp_path):
    with pytest.raises(envelope.InvalidTransitionError):
        store.rule_admissibility("case-008-never-filed", [{"name": "check", "passed": True}])


# =====================================================================
# Decision / adjudication: the authority boundary
# =====================================================================

def test_decide_requires_authority_verifier_configured(store, tmp_path):
    _admitted_case(store, tmp_path, "case-010")
    with pytest.raises(envelope.AuthorityVerifierRequiredError):
        store.decide("case-010", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement")


def test_decide_fails_closed_on_explicit_rejection(store, tmp_path):
    _admitted_case(store, tmp_path, "case-011")
    store.authority_verifier = NonProductionTestAuthorityVerifier(None)
    with pytest.raises(envelope.AuthorityVerificationRejectedError):
        store.decide("case-011", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement")


def test_decide_fails_closed_on_wrong_scope(store, tmp_path):
    _admitted_case(store, tmp_path, "case-012")
    wrong_scope_authority = envelope.VerifiedAuthority(
        principal_id="justice-01",
        authority_scope=("adjudicate:some-other-case",),
        verification_method="test-harness-non-production",
        verified_at=envelope._now(),
        attestation_reference="ref-1",
    )
    store.authority_verifier = NonProductionTestAuthorityVerifier(wrong_scope_authority)
    with pytest.raises(envelope.AuthorityScopeError) as exc_info:
        store.decide("case-012", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement")
    assert "case_id" in str(exc_info.value)


def test_decide_requires_decision_evidence(store, tmp_path):
    _admitted_case(store, tmp_path, "case-013")
    store.authority_verifier = NonProductionTestAuthorityVerifier(_valid_authority("case-013"))
    with pytest.raises(envelope.AcceptanceEvidenceMissingError):
        store.decide("case-013", court.APPROVED, [], "why", "statement")


def test_decide_requires_admitted_stage(store, tmp_path):
    _filed_case(store, tmp_path, "case-014")  # still FILED, not ADMITTED
    store.authority_verifier = NonProductionTestAuthorityVerifier(_valid_authority("case-014"))
    with pytest.raises(envelope.InvalidTransitionError):
        store.decide("case-014", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement")


def test_decide_rejects_invalid_ruling_value(store, tmp_path):
    _admitted_case(store, tmp_path, "case-015")
    with pytest.raises(ValueError):
        store.decide("case-015", "MAYBE", [{"type": "log", "ref": "x"}], "why", "statement")


def test_valid_decision_approved_reaches_terminal_stage(store, tmp_path):
    record = _decided_case(store, tmp_path, "case-016", ruling=court.APPROVED)
    assert record["case_stage"] == court.APPROVED
    assert record["decision_authority"]["principal_id"] == "justice-01"
    assert record["decision_authority"]["attestation_reference"] == "test-attestation-ref-0001"


def test_valid_decision_rejected_reaches_terminal_stage(store, tmp_path):
    record = _decided_case(store, tmp_path, "case-017", ruling=court.REJECTED)
    assert record["case_stage"] == court.REJECTED


def test_replaying_identical_decision_is_idempotent(store, tmp_path):
    _admitted_case(store, tmp_path, "case-018")
    verifier = NonProductionTestAuthorityVerifier(_valid_authority("case-018"))
    store.authority_verifier = verifier
    first = store.decide(
        "case-018", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement"
    )
    second = store.decide(
        "case-018", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement"
    )
    assert first == second
    events = store.reconstruct("case-018")["execution_events"]
    assert sum(1 for e in events if e["transition"] == "DECIDED") == 1


def test_a_different_decision_conflicts(store, tmp_path):
    _admitted_case(store, tmp_path, "case-019")
    store.authority_verifier = NonProductionTestAuthorityVerifier(_valid_authority("case-019"))
    store.decide("case-019", court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement")
    with pytest.raises(envelope.AuthorityConflictError):
        store.decide("case-019", court.REJECTED, [{"type": "log", "ref": "y"}], "different why", "statement")


# =====================================================================
# Terminal-state closure: nothing leaves a terminal stage
# =====================================================================

@pytest.mark.parametrize(
    "build_terminal_case,expected_stage",
    [
        (lambda s, t, cid: s.file_case(cid, "1", "", []), court.QUARANTINED),
        (
            lambda s, t, cid: (
                _filed_case(s, t, cid),
                s.rule_admissibility(cid, [{"name": "c", "passed": False}]),
            )[-1],
            court.INADMISSIBLE,
        ),
        (lambda s, t, cid: _decided_case(s, t, cid, ruling=court.APPROVED), court.APPROVED),
        (lambda s, t, cid: _decided_case(s, t, cid, ruling=court.REJECTED), court.REJECTED),
    ],
)
def test_terminal_stage_rejects_every_further_transition(
    store, tmp_path, build_terminal_case, expected_stage
):
    case_id = f"terminal-{expected_stage.lower()}"
    record = build_terminal_case(store, tmp_path, case_id)
    assert record["case_stage"] == expected_stage

    with pytest.raises(envelope.InvalidTransitionError):
        store.rule_admissibility(case_id, [{"name": "c", "passed": True}])

    with pytest.raises(envelope.InvalidTransitionError):
        store.quarantine_case(case_id, "2", reason="discovered problem later")

    if expected_stage != court.APPROVED and expected_stage != court.REJECTED:
        store.authority_verifier = NonProductionTestAuthorityVerifier(_valid_authority(case_id))
        with pytest.raises(envelope.InvalidTransitionError):
            store.decide(case_id, court.APPROVED, [{"type": "log", "ref": "x"}], "why", "statement")


# =====================================================================
# Appeal: never a reopening, always a new case citing the closed one
# =====================================================================

def test_appeal_references_a_terminal_case_without_mutating_it(store, tmp_path):
    decided = _decided_case(store, tmp_path, "case-020", ruling=court.REJECTED)
    original_ledger_hash = envelope._ledger_content_hash(store._read_ledger("case-020"))

    artifact = _write(tmp_path / "appeal-evidence.txt", "new evidence")
    appeal = store.file_case(
        "case-020-appeal",
        "1",
        "the original ruling misapplied the evidence",
        [str(artifact)],
        appeal_of={"case_id": "case-020", "decision_content_hash": original_ledger_hash},
    )

    assert appeal["case_stage"] == court.FILED
    assert appeal["appeal_of"]["case_id"] == "case-020"
    # the original case's ledger is byte-identical after the appeal is filed
    assert envelope._ledger_content_hash(store._read_ledger("case-020")) == original_ledger_hash
    assert store.get("case-020")["case_stage"] == court.REJECTED


def test_appeal_of_nonexistent_case_is_rejected(store, tmp_path):
    artifact = _write(tmp_path / "evidence.txt", "content")
    with pytest.raises(court.InvalidAppealReferenceError):
        store.file_case(
            "case-021-appeal",
            "1",
            "claim",
            [str(artifact)],
            appeal_of={"case_id": "no-such-case", "decision_content_hash": "deadbeef"},
        )


def test_appeal_of_non_terminal_case_is_rejected(store, tmp_path):
    _admitted_case(store, tmp_path, "case-022")  # ADMITTED, not yet terminal
    artifact = _write(tmp_path / "evidence.txt", "content")
    with pytest.raises(court.InvalidAppealReferenceError):
        store.file_case(
            "case-022-appeal",
            "1",
            "claim",
            [str(artifact)],
            appeal_of={"case_id": "case-022", "decision_content_hash": "irrelevant"},
        )


def test_appeal_with_stale_or_wrong_hash_is_rejected(store, tmp_path):
    _decided_case(store, tmp_path, "case-023", ruling=court.APPROVED)
    artifact = _write(tmp_path / "evidence.txt", "content")
    with pytest.raises(court.InvalidAppealReferenceError):
        store.file_case(
            "case-023-appeal",
            "1",
            "claim",
            [str(artifact)],
            appeal_of={"case_id": "case-023", "decision_content_hash": "not-the-real-hash"},
        )


# =====================================================================
# Ledger integrity: fail closed, never trust a corrupted authoritative ledger
# =====================================================================

def test_corrupted_ledger_fails_closed_on_read(store, tmp_path):
    _filed_case(store, tmp_path, "case-030")
    ledger_path = store._ledger_path("case-030")
    with open(ledger_path, "a") as f:
        f.write("not json at all\n")
    with pytest.raises(envelope.LedgerIntegrityError):
        store.get("case-030")


def test_corrupted_ledger_blocks_further_transitions(store, tmp_path):
    _filed_case(store, tmp_path, "case-031")
    ledger_path = store._ledger_path("case-031")
    with open(ledger_path, "a") as f:
        f.write("{ this is not valid json\n")
    with pytest.raises(envelope.LedgerIntegrityError):
        store.rule_admissibility("case-031", [{"name": "c", "passed": True}])


def test_case_id_validation_is_reused_from_envelope(store, tmp_path):
    with pytest.raises(envelope.InvalidMissionIdError):
        store.file_case("../escape", "1", "claim", [])
