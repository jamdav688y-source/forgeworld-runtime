"""Tests for mission-trajectory instrumentation (evidence_envelope/trajectory.py).

Everything here is exercised through tmp_path stores, consistent with how
envelope.py itself has always been tested: this module ships no committed
instance data, only instrumentation, its tests, and a demonstration that
backfill extraction genuinely works against this repository's real,
git-verifiable commit history.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import envelope  # noqa: E402
import trajectory  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _full_kwargs(run_id, mission_class="mc-1", **overrides):
    kwargs = dict(
        run_id=run_id,
        mission_id=f"mission-for-{run_id}",
        parent_run_id=trajectory.NOT_APPLICABLE,
        mission_class=mission_class,
        provenance_kind=trajectory.RECORD_CONTEMPORANEOUS,
        provenance_extraction_method="recorded_live_during_execution",
        provenance_confidence=trajectory.CONFIDENCE_VERIFIED,
        start_timestamp="2026-08-25T00:00:00Z",
        completion_timestamp="2026-08-25T01:00:00Z",
        starting_commit="a" * 40,
        ending_commit="b" * 40,
        environment_fingerprint="python3.11.15-linux",
        input_reference=trajectory.UNKNOWN,
        declared_acceptance_criteria=trajectory.UNKNOWN,
        authority_boundary="bounded_corrective_mission",
        initial_capability_state_reference=trajectory.UNKNOWN,
        resulting_capability_state_reference=trajectory.UNKNOWN,
        tests_attempted=10,
        tests_passed=10,
        tests_failed=0,
        unsupported_claim_count=0,
        human_intervention_count=0,
        rework_cycle_count=0,
        execution_outcome="SUCCESS",
        failure_classification=trajectory.NOT_APPLICABLE,
        evidence_references=[{"type": "test_output", "ref": "pytest -v"}],
        artifact_identifiers=["b" * 40],
        known_limitations=[],
    )
    kwargs.update(overrides)
    return kwargs


def _minimal_record(run_id, mission_class="mc-1", **overrides):
    return trajectory.build_trajectory_record(**_full_kwargs(run_id, mission_class, **overrides))


# 1. Valid records serialize and deserialize deterministically.
def test_valid_record_serializes_and_deserializes_deterministically():
    record = _minimal_record("run-1")
    serialized = json.dumps(record, sort_keys=True)
    reloaded = json.loads(serialized)
    assert reloaded == record
    assert json.dumps(reloaded, sort_keys=True) == serialized


# 2. Required identifiers cannot be omitted.
def test_required_identifiers_cannot_be_omitted():
    kwargs = _full_kwargs("run-2")
    del kwargs["run_id"]
    with pytest.raises(TypeError):
        trajectory.build_trajectory_record(**kwargs)

    with pytest.raises(envelope.InvalidMissionIdError):
        trajectory.build_trajectory_record(**_full_kwargs("run-2b", mission_id=""))

    with pytest.raises(envelope.InvalidMissionIdError):
        trajectory.build_trajectory_record(**_full_kwargs("../escape"))


# 3. Schema versions are preserved.
def test_schema_version_is_preserved(tmp_path):
    record = _minimal_record("run-3")
    assert record["schema_version"] == trajectory.SCHEMA_VERSION
    store = trajectory.TrajectoryStore(tmp_path / "store")
    store.record_run(record)
    assert store.get_run("run-3")["schema_version"] == trajectory.SCHEMA_VERSION


# 4. Missing measurements are not silently converted to zero.
def test_missing_measurements_are_not_converted_to_zero():
    record = _minimal_record(
        "run-4",
        tests_passed=trajectory.UNMEASURED,
        human_intervention_count=trajectory.UNKNOWN,
        rework_cycle_count=trajectory.NOT_APPLICABLE,
    )
    assert record["tests_passed"]["value"] == trajectory.UNMEASURED
    assert record["tests_passed"]["value"] != 0
    assert record["human_intervention_count"]["value"] == trajectory.UNKNOWN
    assert record["rework_cycle_count"]["value"] == trajectory.NOT_APPLICABLE
    assert record["measurement_availability"]["tests_passed"] == trajectory.UNMEASURED
    assert record["measurement_availability"]["human_intervention_count"] == trajectory.UNKNOWN
    assert record["measurement_availability"]["rework_cycle_count"] == trajectory.NOT_APPLICABLE
    assert record["measurement_availability"]["tests_attempted"] == "PRESENT"


# 5. Observed and interpreted data remain distinguishable.
def test_observed_and_interpreted_data_remain_distinguishable():
    record = _minimal_record(
        "run-5",
        tests_passed=trajectory.Measurement(value=9, provenance=trajectory.OBSERVED, source_reference="pytest run"),
        known_limitations=trajectory.Measurement(
            value=["may not generalize beyond this run"], provenance=trajectory.UNVERIFIED_INTERPRETATION
        ),
    )
    assert record["tests_passed"]["provenance"] == trajectory.OBSERVED
    assert record["known_limitations"]["provenance"] == trajectory.UNVERIFIED_INTERPRETATION
    assert record["tests_passed"]["provenance"] != record["known_limitations"]["provenance"]


def test_invalid_provenance_kind_is_rejected():
    with pytest.raises(trajectory.InvalidTrajectoryRecordError):
        trajectory.build_trajectory_record(
            **_full_kwargs("run-5b", tests_passed=trajectory.Measurement(value=1, provenance="MADE_UP_KIND"))
        )


# 6. Compatible runs can be compared deterministically.
def test_compatible_runs_compare_deterministically():
    a = _minimal_record("run-6a", mission_class="mc-cmp", tests_passed=8, tests_failed=2)
    b = _minimal_record("run-6b", mission_class="mc-cmp", tests_passed=10, tests_failed=0)
    r1 = trajectory.compare_runs(a, b)
    r2 = trajectory.compare_runs(a, b)
    assert r1.to_dict() == r2.to_dict()
    assert r1.compatible is True
    passed_cmp = next(c for c in r1.metric_comparisons if c.metric == "tests_passed")
    assert passed_cmp.classification == trajectory.IMPROVED
    assert passed_cmp.value_a == 8 and passed_cmp.value_b == 10


# 7. Incompatible runs cannot produce a false improvement result.
def test_incompatible_runs_cannot_produce_false_improvement():
    a = _minimal_record("run-7a", mission_class="mc-A", tests_passed=1)
    b = _minimal_record("run-7b", mission_class="mc-B", tests_passed=100)
    result = trajectory.compare_runs(a, b)
    assert result.compatible is False
    assert result.metric_comparisons == ()
    assert "mission_class mismatch" in result.incompatibility_reason


# A backfilled record compared against a contemporaneous one must never be
# silently indistinguishable from a same-provenance comparison: the
# distinction is surfaced directly in the comparison result.
def test_mixed_provenance_is_surfaced_in_comparison_result():
    a = _minimal_record("run-mp-a", mission_class="mc-mp", provenance_kind=trajectory.RECORD_CONTEMPORANEOUS)
    b = _minimal_record(
        "run-mp-b", mission_class="mc-mp",
        provenance_kind=trajectory.RECORD_BACKFILLED,
        provenance_extraction_method="git_log_reconstruction",
        provenance_confidence=trajectory.CONFIDENCE_PARTIAL,
    )
    result = trajectory.compare_runs(a, b)
    assert result.compatible is True
    assert result.provenance_kind_a == trajectory.RECORD_CONTEMPORANEOUS
    assert result.provenance_kind_b == trajectory.RECORD_BACKFILLED
    assert result.mixed_provenance_warning is not None
    assert "CONTEMPORANEOUS" in result.mixed_provenance_warning
    assert "BACKFILLED" in result.mixed_provenance_warning
    # Surfaced on incompatible pairs too -- never dropped en route to an
    # early return.
    c = _minimal_record("run-mp-c", mission_class="mc-different", provenance_kind=trajectory.RECORD_BACKFILLED,
                          provenance_extraction_method="git_log_reconstruction",
                          provenance_confidence=trajectory.CONFIDENCE_PARTIAL)
    incompatible_result = trajectory.compare_runs(a, c)
    assert incompatible_result.compatible is False
    assert incompatible_result.mixed_provenance_warning is not None


def test_same_provenance_kind_has_no_mixed_provenance_warning():
    a = _minimal_record("run-sp-a", mission_class="mc-sp")
    b = _minimal_record("run-sp-b", mission_class="mc-sp")
    result = trajectory.compare_runs(a, b)
    assert result.mixed_provenance_warning is None
    assert result.provenance_kind_a == result.provenance_kind_b == trajectory.RECORD_CONTEMPORANEOUS


def test_observed_provenance_cannot_be_paired_with_absence_sentinel():
    with pytest.raises(trajectory.InvalidTrajectoryRecordError):
        _minimal_record(
            "run-contradiction",
            tests_passed=trajectory.Measurement(value=trajectory.UNKNOWN, provenance=trajectory.OBSERVED),
        )


def test_bare_absence_sentinel_defaults_to_system_asserted_not_observed():
    record = _minimal_record("run-default-sentinel", tests_passed=trajectory.UNMEASURED)
    assert record["tests_passed"]["provenance"] == trajectory.SYSTEM_ASSERTED


def test_mismatched_schema_version_is_incompatible():
    a = _minimal_record("run-7c", mission_class="mc-schema")
    b = dict(_minimal_record("run-7d", mission_class="mc-schema"))
    b["schema_version"] = 999
    result = trajectory.compare_runs(a, b)
    assert result.compatible is False
    assert "schema_version mismatch" in result.incompatibility_reason


def test_comparing_a_run_against_itself_is_rejected():
    a = _minimal_record("run-7e", mission_class="mc-self")
    result = trajectory.compare_runs(a, a)
    assert result.compatible is False


# 8. Regression is preserved.
def test_regression_is_preserved():
    a = _minimal_record("run-8a", mission_class="mc-reg", tests_failed=0, human_intervention_count=0)
    b = _minimal_record("run-8b", mission_class="mc-reg", tests_failed=3, human_intervention_count=2)
    result = trajectory.compare_runs(a, b)
    failed_cmp = next(c for c in result.metric_comparisons if c.metric == "tests_failed")
    intervention_cmp = next(c for c in result.metric_comparisons if c.metric == "human_intervention_count")
    assert failed_cmp.classification == trajectory.REGRESSED
    assert intervention_cmp.classification == trajectory.REGRESSED
    # Regressions are not filtered out or demoted -- the full breakdown is present.
    assert len(result.metric_comparisons) == len(trajectory._METRIC_DIRECTION)


# 9. Indeterminate evidence remains indeterminate.
def test_indeterminate_evidence_remains_indeterminate():
    a = _minimal_record("run-9a", mission_class="mc-ind", tests_passed=trajectory.UNKNOWN)
    b = _minimal_record("run-9b", mission_class="mc-ind", tests_passed=10)
    result = trajectory.compare_runs(a, b)
    passed_cmp = next(c for c in result.metric_comparisons if c.metric == "tests_passed")
    assert passed_cmp.classification == trajectory.INDETERMINATE


# 10. Malformed evidence references fail validation.
def test_malformed_evidence_references_fail_validation():
    with pytest.raises(trajectory.InvalidTrajectoryRecordError):
        _minimal_record("run-10a", evidence_references=[{"type": "log"}])  # missing "ref"
    with pytest.raises(trajectory.InvalidTrajectoryRecordError):
        _minimal_record("run-10b", evidence_references=[{"ref": "x"}])  # missing "type"
    with pytest.raises(trajectory.InvalidTrajectoryRecordError):
        _minimal_record("run-10c", evidence_references="not-a-list")
    with pytest.raises(trajectory.InvalidTrajectoryRecordError):
        _minimal_record("run-10d", evidence_references=[{"type": "", "ref": "x"}])


# 11. Existing evidence-envelope consumers remain compatible.
def test_existing_evidence_envelope_tests_remain_compatible():
    result = subprocess.run(
        ["pytest", "evidence_envelope/tests/test_envelope.py", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# 12. Existing test suites do not regress (and operational ledgers stay untouched).
def test_existing_capability_tests_and_ledgers_remain_unchanged():
    result = subprocess.run(
        ["pytest", "capabilities/tests/", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    diff = subprocess.run(
        ["git", "diff", "--exit-code", "--", "capabilities/history.jsonl", "router/decisions.jsonl"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert diff.returncode == 0, "operational ledger(s) changed:\n" + diff.stdout


# -- storage behavior ---------------------------------------------------

def test_trajectory_store_round_trip(tmp_path):
    store = trajectory.TrajectoryStore(tmp_path / "store")
    record = _minimal_record("run-rt", mission_class="mc-rt")
    stored = store.record_run(record)
    assert stored == record
    assert store.get_run("run-rt") == record
    assert store.list_runs() == [record]
    assert store.list_runs(mission_class="mc-rt") == [record]
    assert store.list_runs(mission_class="nonexistent") == []


def test_trajectory_store_identical_replay_is_idempotent(tmp_path):
    store = trajectory.TrajectoryStore(tmp_path / "store")
    record = _minimal_record("run-idem")
    store.record_run(record)
    store.record_run(record)
    assert len(store._read_all()) == 1


def test_trajectory_store_conflicting_replay_is_rejected(tmp_path):
    store = trajectory.TrajectoryStore(tmp_path / "store")
    store.record_run(_minimal_record("run-conflict", tests_passed=5))
    different = _minimal_record("run-conflict", tests_passed=99)
    with pytest.raises(trajectory.TrajectoryConflictError):
        store.record_run(different)
    assert len(store._read_all()) == 1


def test_trajectory_store_corrupted_ledger_fails_closed(tmp_path):
    store = trajectory.TrajectoryStore(tmp_path / "store")
    store.record_run(_minimal_record("run-corrupt"))
    store.ledger_path.write_text('{"run_id": "broken"')  # no closing brace, no newline

    with pytest.raises(envelope.LedgerIntegrityError):
        store._read_all()
    with pytest.raises(envelope.LedgerIntegrityError):
        store.get_run("run-corrupt")


def test_parent_run_id_links_rework_cycles(tmp_path):
    store = trajectory.TrajectoryStore(tmp_path / "store")
    original = _minimal_record("run-parent", mission_class="mc-repair")
    store.record_run(original)
    rework = _minimal_record(
        "run-child", mission_class="mc-repair", parent_run_id="run-parent", rework_cycle_count=1
    )
    store.record_run(rework)
    assert store.get_run("run-child")["parent_run_id"] == "run-parent"


# -- backfill: demonstrated against this repository's real commit history --

def test_backfill_extraction_matches_real_git_history():
    facts_a = trajectory.extract_git_commit_facts(
        REPO_ROOT, "9633d36", "evidence_envelope/tests/test_envelope.py"
    )
    facts_b = trajectory.extract_git_commit_facts(
        REPO_ROOT, "96658e7", "evidence_envelope/tests/test_envelope.py"
    )
    assert facts_a["ending_commit"] == "9633d367e406d57ade6696024d7c5f7565f0e380"
    assert facts_a["starting_commit"] == "4851cd635c518ef50ffe73e1441bfc6d0bc7748e"
    assert facts_b["starting_commit"] == facts_a["ending_commit"]
    # These counts are independently reproducible: `git show <sha>:<path> | grep -c '^def test_'`
    assert facts_a["test_function_definitions_at_commit"] == 12
    assert facts_b["test_function_definitions_at_commit"] == 41


def test_backfilled_record_marks_unmeasured_fields_unknown_not_fabricated(tmp_path):
    facts = trajectory.extract_git_commit_facts(
        REPO_ROOT, "9633d36", "evidence_envelope/tests/test_envelope.py"
    )
    record = trajectory.build_trajectory_record(
        run_id="backfill-9633d36",
        mission_id="FW-MISSION-EVIDENCE-ENVELOPE-001",
        parent_run_id=trajectory.NOT_APPLICABLE,
        mission_class="bounded_envelope_implementation",
        provenance_kind=trajectory.RECORD_BACKFILLED,
        provenance_extraction_method="git_log_reconstruction",
        provenance_confidence=trajectory.CONFIDENCE_PARTIAL,
        start_timestamp=trajectory.UNKNOWN,
        completion_timestamp=trajectory.Measurement(
            value=facts["completion_timestamp"], provenance=trajectory.OBSERVED,
            source_reference=f"git show -s --format=%cI {facts['ending_commit']}",
        ),
        starting_commit=trajectory.Measurement(
            value=facts["starting_commit"], provenance=trajectory.OBSERVED,
            source_reference="git rev-parse 9633d36^",
        ),
        ending_commit=trajectory.Measurement(
            value=facts["ending_commit"], provenance=trajectory.OBSERVED,
            source_reference="git rev-parse 9633d36",
        ),
        environment_fingerprint=trajectory.UNKNOWN,
        input_reference=trajectory.UNKNOWN,
        declared_acceptance_criteria=trajectory.UNKNOWN,
        authority_boundary=trajectory.UNKNOWN,
        initial_capability_state_reference=trajectory.NOT_APPLICABLE,
        resulting_capability_state_reference=trajectory.Measurement(
            value=facts["ending_commit"], provenance=trajectory.OBSERVED,
        ),
        tests_attempted=trajectory.Measurement(
            value=facts["test_function_definitions_at_commit"], provenance=trajectory.DERIVED,
            source_reference=facts["source_reference"],
        ),
        # Not re-executed historically -- never fabricated as a pass/fail count.
        tests_passed=trajectory.UNKNOWN,
        tests_failed=trajectory.UNKNOWN,
        unsupported_claim_count=trajectory.UNKNOWN,
        human_intervention_count=trajectory.UNKNOWN,
        rework_cycle_count=trajectory.UNKNOWN,
        execution_outcome=trajectory.UNKNOWN,
        failure_classification=trajectory.NOT_APPLICABLE,
        evidence_references=[{"type": "commit", "ref": facts["ending_commit"]}],
        artifact_identifiers=[facts["ending_commit"]],
        known_limitations=[
            "tests_passed/tests_failed were not re-executed for this historical commit; "
            "only a source-level test_function count was derived from git history"
        ],
    )

    assert record["provenance"]["kind"] == trajectory.RECORD_BACKFILLED
    assert record["provenance"]["extraction_method"] == "git_log_reconstruction"
    assert record["tests_passed"]["value"] == trajectory.UNKNOWN
    assert record["tests_attempted"]["value"] == 12
    assert record["tests_attempted"]["provenance"] == trajectory.DERIVED

    store = trajectory.TrajectoryStore(tmp_path / "store")
    store.record_run(record)
    reloaded = store.get_run("backfill-9633d36")
    assert reloaded["tests_attempted"]["value"] == 12
    assert reloaded["measurement_availability"]["tests_passed"] == trajectory.UNKNOWN
