"""Mission-trajectory instrumentation, extending the mission-and-evidence
envelope (envelope.py) rather than duplicating it.

DISCOVERED ARCHITECTURE (see the completion report for the full survey):
envelope.py is the only code-backed, tested mission lifecycle and evidence
ledger in this repository. router/decisions.jsonl and
capabilities/history.jsonl are a separate, older, simpler concept
(capability-routing outcomes, unlocked, non-atomic, no schema versioning)
and are explicitly untouched operational ledgers. The various RPG-flavored
text files under events/, consequences/, memory/, etc. are static
narrative scaffolding with no reading/writing code anywhere in the
repository -- not an evidence architecture.

A trajectory record is a different unit than a mission envelope: an
envelope tracks ONE mission_id's lifecycle (BRONZE -> ... -> GOLD); a
trajectory tracks ONE RUN of a mission (or of an experiment in a
mission_class), so the same mission_id or class can have many runs to
compare over time, and forcing that through envelope.py's BRONZE/SILVER/
GOLD state machine would misrepresent it. This module therefore
introduces its own record shape, but reuses envelope.py's already-built
and already-tested machinery directly rather than re-implementing it:
validate_mission_id() for every identifier here, _atomic_write_bytes() /
_FileLock() / _serialize_ledger() for durable, locked, atomic storage,
and LedgerIntegrityError for the identical corrupted-ledger failure mode.

THIS MODULE INSTRUMENTS EVIDENCE. IT DOES NOT ASSERT THAT IMPROVEMENT HAS
OCCURRED, DOES NOT COMPUTE A COMPOSITE SCORE, AND DOES NOT AUTHORIZE ANY
PUBLIC OR COMMERCIAL CLAIM. compare_runs() returns per-metric, evidenced
classifications only; nothing in this module decides those classifications
mean the system is "improving," and nothing here publishes anything.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import envelope

SCHEMA_VERSION = 1

# -- explicit absence sentinels: an absent measurement is always one of
# these three strings, never silently coerced to 0, "", or None. ---------
UNKNOWN = "UNKNOWN"
UNMEASURED = "UNMEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"
_ABSENCE_SENTINELS = (UNKNOWN, UNMEASURED, NOT_APPLICABLE)

# -- provenance: what KIND of statement a value is. Every measurement in a
# trajectory record must carry one of these; an interpretation can never
# silently occupy a factual field because the field structurally demands
# this tag. This validates that a tag was chosen from the six below --
# it cannot and does not verify that the tag is *true* (e.g. that a value
# tagged OBSERVED really was observed rather than guessed). That is the
# same honesty boundary envelope.py documents for AuthorityVerifier: this
# module enforces the presence of a provenance declaration, not the
# truthfulness of the caller who makes it. ---------------------------------
OBSERVED = "OBSERVED"
DERIVED = "DERIVED"
HUMAN_ASSERTED = "HUMAN_ASSERTED"
SYSTEM_ASSERTED = "SYSTEM_ASSERTED"
UNVERIFIED_INTERPRETATION = "UNVERIFIED_INTERPRETATION"
AUTHORIZED_CONCLUSION = "AUTHORIZED_CONCLUSION"
PROVENANCE_KINDS = (
    OBSERVED, DERIVED, HUMAN_ASSERTED, SYSTEM_ASSERTED,
    UNVERIFIED_INTERPRETATION, AUTHORIZED_CONCLUSION,
)

RECORD_CONTEMPORANEOUS = "CONTEMPORANEOUS"
RECORD_BACKFILLED = "BACKFILLED"
_RECORD_KINDS = (RECORD_CONTEMPORANEOUS, RECORD_BACKFILLED)

CONFIDENCE_VERIFIED = "VERIFIED"
CONFIDENCE_PARTIAL = "PARTIAL"
CONFIDENCE_UNVERIFIED = "UNVERIFIED"
_CONFIDENCE_LEVELS = (CONFIDENCE_VERIFIED, CONFIDENCE_PARTIAL, CONFIDENCE_UNVERIFIED)

# The fields a trajectory record wraps as Measurements (value + provenance
# + optional source_reference), i.e. everything that is a *measurement*
# rather than a structural identifier.
_MEASUREMENT_FIELDS = (
    "start_timestamp",
    "completion_timestamp",
    "starting_commit",
    "ending_commit",
    "environment_fingerprint",
    "input_reference",
    "declared_acceptance_criteria",
    "authority_boundary",
    "initial_capability_state_reference",
    "resulting_capability_state_reference",
    "tests_attempted",
    "tests_passed",
    "tests_failed",
    "unsupported_claim_count",
    "human_intervention_count",
    "rework_cycle_count",
    "execution_outcome",
    "failure_classification",
    "evidence_references",
    "artifact_identifiers",
    "known_limitations",
)

_NONNEGATIVE_INT_FIELDS = (
    "tests_attempted", "tests_passed", "tests_failed",
    "unsupported_claim_count", "human_intervention_count", "rework_cycle_count",
)

# Metrics compare_runs() will classify, and which direction is "better".
# Deliberately narrow: only fields with an unambiguous, non-interpretive
# direction are compared this way. execution_outcome, failure_classification,
# timestamps, commits, and references are facts to read, not numbers to
# grade -- comparing them as "improved/regressed" would itself be an
# interpretation smuggled into a factual mechanism.
_METRIC_DIRECTION = {
    "tests_passed": "higher_is_better",
    "tests_failed": "lower_is_better",
    "unsupported_claim_count": "lower_is_better",
    "human_intervention_count": "lower_is_better",
    "rework_cycle_count": "lower_is_better",
}

IMPROVED = "IMPROVED"
REGRESSED = "REGRESSED"
UNCHANGED = "UNCHANGED"
INDETERMINATE = "INDETERMINATE"


class TrajectoryError(envelope.EnvelopeError):
    """Base error for trajectory instrumentation."""


class InvalidTrajectoryRecordError(TrajectoryError):
    """A trajectory record failed schema/shape validation."""


class TrajectoryConflictError(TrajectoryError):
    """A run_id already exists in the ledger with different content.

    Trajectory records are append-only, mirroring envelope.py's mission
    records: an identical re-record of the same run_id is an idempotent
    no-op; a different one for the same run_id is refused outright, never
    silently overwritten.
    """


@dataclass(frozen=True)
class Measurement:
    """One field of a trajectory record: a value (which may itself be one
    of UNKNOWN/UNMEASURED/NOT_APPLICABLE) plus the mandatory tag saying
    what *kind* of statement it is, plus an optional pointer to where it
    came from."""

    value: Any
    provenance: str
    source_reference: Optional[str] = None

    def to_dict(self) -> dict:
        return {"value": self.value, "provenance": self.provenance, "source_reference": self.source_reference}


def _coerce_measurement(value: Any, *, default_provenance: str = OBSERVED) -> Measurement:
    if isinstance(value, Measurement):
        return value
    if value in _ABSENCE_SENTINELS:
        # A bare sentinel (the ergonomic, common case for "I don't have
        # this") defaults to SYSTEM_ASSERTED, never OBSERVED -- OBSERVED
        # paired with an absence sentinel is a contradiction rejected by
        # _validate_measurement, so a caller who wants OBSERVED must be
        # supplying a real observed value, not marking something absent.
        return Measurement(value=value, provenance=SYSTEM_ASSERTED)
    return Measurement(value=value, provenance=default_provenance)


def _validate_measurement(field_name: str, m: Measurement) -> None:
    if m.provenance not in PROVENANCE_KINDS:
        raise InvalidTrajectoryRecordError(
            f"{field_name}.provenance {m.provenance!r} is not one of {PROVENANCE_KINDS}"
        )
    if m.value in _ABSENCE_SENTINELS and m.provenance == OBSERVED:
        # A contradiction, not a style nit: OBSERVED means something was
        # actually seen. An absence sentinel means nothing was. Rejecting
        # this combination closes the specific case where a free-text
        # field's real value could otherwise collide with one of the
        # sentinel strings and be indistinguishable, in
        # measurement_availability, from a genuinely absent measurement.
        # An absence is still representable -- just not tagged OBSERVED.
        raise InvalidTrajectoryRecordError(
            f"{field_name} cannot be both an absence sentinel ({m.value!r}) and provenance=OBSERVED; "
            "use SYSTEM_ASSERTED (or another non-OBSERVED provenance) for a recorded absence"
        )
    if field_name in _NONNEGATIVE_INT_FIELDS and m.value not in _ABSENCE_SENTINELS:
        if not isinstance(m.value, int) or isinstance(m.value, bool) or m.value < 0:
            raise InvalidTrajectoryRecordError(
                f"{field_name}.value must be a non-negative int or an absence sentinel, got {m.value!r}"
            )
    if field_name == "evidence_references" and m.value not in _ABSENCE_SENTINELS:
        _validate_evidence_references(m.value)
    if field_name == "artifact_identifiers" and m.value not in _ABSENCE_SENTINELS:
        if not isinstance(m.value, list) or not all(isinstance(a, str) and a for a in m.value):
            raise InvalidTrajectoryRecordError(
                "artifact_identifiers must be a list of non-empty strings or an absence sentinel"
            )
    if field_name == "known_limitations" and m.value not in _ABSENCE_SENTINELS:
        if not isinstance(m.value, list) or not all(isinstance(a, str) for a in m.value):
            raise InvalidTrajectoryRecordError(
                "known_limitations must be a list of strings or an absence sentinel"
            )


def _validate_evidence_references(refs: Any) -> None:
    """Evidence references reuse envelope.py's established shape for
    evidence_artifacts: {"type": str, "ref": str}. A malformed reference
    (wrong shape, missing/empty keys) fails validation rather than being
    silently accepted."""
    if not isinstance(refs, list):
        raise InvalidTrajectoryRecordError("evidence_references must be a list or an absence sentinel")
    for i, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise InvalidTrajectoryRecordError(f"evidence_references[{i}] must be an object, got {type(ref).__name__}")
        ref_type = ref.get("type")
        ref_value = ref.get("ref")
        if not isinstance(ref_type, str) or not ref_type.strip():
            raise InvalidTrajectoryRecordError(f"evidence_references[{i}].type must be a non-empty string")
        if not isinstance(ref_value, str) or not ref_value.strip():
            raise InvalidTrajectoryRecordError(f"evidence_references[{i}].ref must be a non-empty string")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_trajectory_record(
    *,
    run_id: str,
    mission_id: str,
    parent_run_id: Any,
    mission_class: str,
    provenance_kind: str,
    provenance_extraction_method: str,
    provenance_confidence: str,
    start_timestamp: Any,
    completion_timestamp: Any,
    starting_commit: Any,
    ending_commit: Any,
    environment_fingerprint: Any,
    input_reference: Any,
    declared_acceptance_criteria: Any,
    authority_boundary: Any,
    initial_capability_state_reference: Any,
    resulting_capability_state_reference: Any,
    tests_attempted: Any,
    tests_passed: Any,
    tests_failed: Any,
    unsupported_claim_count: Any,
    human_intervention_count: Any,
    rework_cycle_count: Any,
    execution_outcome: Any,
    failure_classification: Any,
    evidence_references: Any,
    artifact_identifiers: Any,
    known_limitations: Any,
) -> dict:
    """Build one trajectory record. Every measurement parameter is
    mandatory (no defaults) so a field can never be silently omitted --
    the caller must consciously supply a real value, a Measurement(...)
    with explicit provenance, or one of UNKNOWN/UNMEASURED/NOT_APPLICABLE.
    Nothing here is ever converted to 0 for an absent measurement.

    run_id, mission_id, and parent_run_id (when not NOT_APPLICABLE) are
    validated with envelope.validate_mission_id -- the same canonical,
    path-safe identifier contract already established and tested for
    mission envelopes, reused directly rather than reimplemented.
    """
    run_id = envelope.validate_mission_id(run_id)
    mission_id = envelope.validate_mission_id(mission_id)
    if parent_run_id != NOT_APPLICABLE:
        parent_run_id = envelope.validate_mission_id(parent_run_id)

    if not isinstance(mission_class, str) or not mission_class.strip():
        raise InvalidTrajectoryRecordError("mission_class must be a non-empty string")

    if provenance_kind not in _RECORD_KINDS:
        raise InvalidTrajectoryRecordError(f"provenance_kind must be one of {_RECORD_KINDS}")
    if provenance_confidence not in _CONFIDENCE_LEVELS:
        raise InvalidTrajectoryRecordError(f"provenance_confidence must be one of {_CONFIDENCE_LEVELS}")
    if not isinstance(provenance_extraction_method, str) or not provenance_extraction_method.strip():
        raise InvalidTrajectoryRecordError("provenance_extraction_method must be a non-empty string")

    local_values = locals()
    measurements = {}
    for field_name in _MEASUREMENT_FIELDS:
        m = _coerce_measurement(local_values[field_name])
        _validate_measurement(field_name, m)
        measurements[field_name] = m.to_dict()

    measurement_availability = {
        name: (NOT_APPLICABLE if m["value"] == NOT_APPLICABLE
               else UNMEASURED if m["value"] == UNMEASURED
               else UNKNOWN if m["value"] == UNKNOWN
               else "PRESENT")
        for name, m in measurements.items()
    }

    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "mission_id": mission_id,
        "parent_run_id": parent_run_id,
        "mission_class": mission_class,
        "provenance": {
            "kind": provenance_kind,
            "extraction_method": provenance_extraction_method,
            "confidence": provenance_confidence,
            "recorded_at": _now(),
        },
        **measurements,
        "measurement_availability": measurement_availability,
        "state_transition": {
            "state_before": measurements["initial_capability_state_reference"]["value"],
            "intervention": mission_class,
            "conditions": {
                "authority_boundary": measurements["authority_boundary"]["value"],
                "environment_fingerprint": measurements["environment_fingerprint"]["value"],
            },
            "state_after": measurements["resulting_capability_state_reference"]["value"],
        },
    }
    return record


# ---------------------------------------------------------------------------
# storage: reuses envelope.py's durable-write and locking primitives
# ---------------------------------------------------------------------------

class TrajectoryStore:
    """Append-only ledger of trajectory records, one JSONL file per store
    root. Reuses envelope.py's already-tested durability primitives
    directly: _atomic_write_bytes / _serialize_ledger for the whole-file
    atomic replace, _FileLock for the same bounded, cross-process,
    never-deleted advisory lock, and LedgerIntegrityError for identical
    corrupted-ledger semantics. This is not a second evidence store: it is
    the same storage discipline, applied to a different, smaller record
    shape that does not fit envelope.py's BRONZE/SILVER/GOLD state
    machine.
    """

    def __init__(self, root: Path, lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "trajectory.jsonl"
        self.lock_path = self.root / "trajectory.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    def _read_all(self) -> list:
        if not self.ledger_path.exists():
            return []
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(
                        f"trajectory ledger {self.ledger_path} line {line_number} is not "
                        "newline-terminated (truncated or partially written)"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise envelope.LedgerIntegrityError(
                        f"trajectory ledger {self.ledger_path} line {line_number} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(record, dict) or "run_id" not in record:
                    raise envelope.LedgerIntegrityError(
                        f"trajectory ledger {self.ledger_path} line {line_number} is missing "
                        "required fields"
                    )
                records.append(record)
        return records

    def record_run(self, record: dict) -> dict:
        """Append `record` (as built by build_trajectory_record) durably
        and atomically, under this store's cross-process lock. Identical
        re-recording of the same run_id is an idempotent no-op; recording
        different content under an already-used run_id raises
        TrajectoryConflictError -- run_id identity is append-only, never
        silently overwritten."""
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all()
            existing = next((r for r in records if r["run_id"] == record["run_id"]), None)
            if existing is not None:
                if existing == record:
                    return existing
                raise TrajectoryConflictError(
                    f"run_id {record['run_id']!r} already recorded with different content"
                )
            envelope._atomic_write_bytes(
                self.ledger_path, envelope._serialize_ledger(records + [record])
            )
            return record

    def get_run(self, run_id: str) -> Optional[dict]:
        run_id = envelope.validate_mission_id(run_id)
        return next((r for r in self._read_all() if r["run_id"] == run_id), None)

    def list_runs(self, mission_class: Optional[str] = None) -> list:
        records = self._read_all()
        if mission_class is not None:
            records = [r for r in records if r["mission_class"] == mission_class]
        return records


# ---------------------------------------------------------------------------
# comparison: the smallest deterministic mechanism needed to compare runs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricComparison:
    metric: str
    direction: str
    value_a: Any
    value_b: Any
    classification: str
    reason: str


@dataclass(frozen=True)
class ComparisonResult:
    compatible: bool
    incompatibility_reason: Optional[str]
    run_id_a: str
    run_id_b: str
    mission_class: Optional[str]
    provenance_kind_a: str
    provenance_kind_b: str
    mixed_provenance_warning: Optional[str]
    metric_comparisons: Sequence[MetricComparison] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "compatible": self.compatible,
            "incompatibility_reason": self.incompatibility_reason,
            "run_id_a": self.run_id_a,
            "run_id_b": self.run_id_b,
            "mission_class": self.mission_class,
            "provenance_kind_a": self.provenance_kind_a,
            "provenance_kind_b": self.provenance_kind_b,
            "mixed_provenance_warning": self.mixed_provenance_warning,
            "metric_comparisons": [
                {
                    "metric": c.metric,
                    "direction": c.direction,
                    "value_a": c.value_a,
                    "value_b": c.value_b,
                    "classification": c.classification,
                    "reason": c.reason,
                }
                for c in self.metric_comparisons
            ],
        }


def compare_runs(run_a: dict, run_b: dict) -> ComparisonResult:
    """Compare two trajectory records deterministically. `run_a` is the
    baseline; `run_b` is the candidate being classified relative to it.

    This function never combines metrics into a single score, never
    infers causation, and never emits any kind of "improved overall"
    verdict -- it returns one classification per directly comparable
    metric, each carrying its own evidence (the two raw values), so a
    human or a later, separately authorized layer can review them. A run
    pair judged incompatible returns zero metric comparisons: nothing
    about an incompatible pair can be read as an improvement or a
    regression.

    provenance_kind_a/b and mixed_provenance_warning are always populated
    (even for an incompatible pair) so a BACKFILLED record can never be
    silently compared, or silently read, as if it were CONTEMPORANEOUS:
    the distinction is surfaced in every result, not left to a caller who
    might only look at the metric classifications. This does not verify
    that either record's self-reported provenance is *true* -- build_
    trajectory_record does not and cannot audit a caller's honesty about
    how a value was obtained, the same limitation envelope.py's
    AuthorityVerifier openly documents for identity. What this does
    guarantee is that a mismatch a caller *did* declare is never dropped
    on the way to a comparison result.
    """
    provenance_kind_a = run_a["provenance"]["kind"]
    provenance_kind_b = run_b["provenance"]["kind"]
    mixed_provenance_warning = (
        None if provenance_kind_a == provenance_kind_b else
        f"run_id_a ({run_a['run_id']}) is {provenance_kind_a} while run_id_b ({run_b['run_id']}) "
        f"is {provenance_kind_b}: this comparison mixes a live observation with a historical "
        "reconstruction (or vice versa)"
    )

    if run_a["mission_class"] != run_b["mission_class"]:
        return ComparisonResult(
            compatible=False,
            incompatibility_reason=(
                f"mission_class mismatch: {run_a['mission_class']!r} vs {run_b['mission_class']!r}"
            ),
            run_id_a=run_a["run_id"],
            run_id_b=run_b["run_id"],
            mission_class=None,
            provenance_kind_a=provenance_kind_a,
            provenance_kind_b=provenance_kind_b,
            mixed_provenance_warning=mixed_provenance_warning,
        )
    if run_a["schema_version"] != run_b["schema_version"]:
        return ComparisonResult(
            compatible=False,
            incompatibility_reason=(
                f"schema_version mismatch: {run_a['schema_version']!r} vs {run_b['schema_version']!r}"
            ),
            run_id_a=run_a["run_id"],
            run_id_b=run_b["run_id"],
            mission_class=None,
            provenance_kind_a=provenance_kind_a,
            provenance_kind_b=provenance_kind_b,
            mixed_provenance_warning=mixed_provenance_warning,
        )
    if run_a["run_id"] == run_b["run_id"]:
        return ComparisonResult(
            compatible=False,
            incompatibility_reason="cannot compare a run against itself",
            run_id_a=run_a["run_id"],
            run_id_b=run_b["run_id"],
            mission_class=None,
            provenance_kind_a=provenance_kind_a,
            provenance_kind_b=provenance_kind_b,
            mixed_provenance_warning=mixed_provenance_warning,
        )

    comparisons = []
    for metric, direction in _METRIC_DIRECTION.items():
        value_a = run_a[metric]["value"]
        value_b = run_b[metric]["value"]
        if value_a in _ABSENCE_SENTINELS or value_b in _ABSENCE_SENTINELS:
            comparisons.append(MetricComparison(
                metric=metric, direction=direction, value_a=value_a, value_b=value_b,
                classification=INDETERMINATE,
                reason="not available in both runs",
            ))
            continue
        if value_a == value_b:
            classification = UNCHANGED
        elif direction == "higher_is_better":
            classification = IMPROVED if value_b > value_a else REGRESSED
        else:  # lower_is_better
            classification = IMPROVED if value_b < value_a else REGRESSED
        comparisons.append(MetricComparison(
            metric=metric, direction=direction, value_a=value_a, value_b=value_b,
            classification=classification,
            reason=f"{value_a} -> {value_b} ({direction})",
        ))

    return ComparisonResult(
        compatible=True,
        incompatibility_reason=None,
        run_id_a=run_a["run_id"],
        run_id_b=run_b["run_id"],
        mission_class=run_a["mission_class"],
        provenance_kind_a=provenance_kind_a,
        provenance_kind_b=provenance_kind_b,
        mixed_provenance_warning=mixed_provenance_warning,
        metric_comparisons=tuple(comparisons),
    )


# ---------------------------------------------------------------------------
# backfill: extraction from repository-verifiable artifacts only
# ---------------------------------------------------------------------------

def extract_git_commit_facts(repo_root: Path, commit_sha: str, test_file_relpath: str) -> dict:
    """Extract only what a git commit can actually prove, without
    checking out or mutating the working tree (uses `git show`, which
    reads a historical blob without touching HEAD or the index):

      - the full commit SHA and its parent SHA (ending/starting commit)
      - the commit's own timestamp (completion_timestamp)
      - a count of `def test_` occurrences in a given file's content AT
        that commit, as a DERIVED proxy for tests_attempted (source-level
        test function count, not a runtime-parametrized execution count
        -- labeled accordingly, never claimed to be a live pytest result)

    Every value returned here is independently reproducible by re-running
    the same git commands against this repository; nothing is asserted
    from memory or narrative. Fields this cannot determine (e.g. how many
    tests actually passed when that commit ran, how many humans
    intervened) are the caller's responsibility to mark UNKNOWN --this
    function never fabricates them.
    """
    full_sha = subprocess.run(
        ["git", "rev-parse", commit_sha], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    parent_result = subprocess.run(
        ["git", "rev-parse", f"{commit_sha}^"], cwd=repo_root, capture_output=True, text=True
    )
    starting_commit = parent_result.stdout.strip() if parent_result.returncode == 0 else UNKNOWN

    commit_date = subprocess.run(
        ["git", "show", "-s", "--format=%cI", commit_sha], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()

    file_result = subprocess.run(
        ["git", "show", f"{commit_sha}:{test_file_relpath}"], cwd=repo_root, capture_output=True, text=True
    )
    if file_result.returncode == 0:
        test_def_count = sum(
            1 for line in file_result.stdout.splitlines() if line.startswith("def test_")
        )
    else:
        test_def_count = UNKNOWN

    return {
        "ending_commit": full_sha,
        "starting_commit": starting_commit,
        "completion_timestamp": commit_date,
        "test_function_definitions_at_commit": test_def_count,
        "source_reference": f"git show {full_sha}:{test_file_relpath}",
    }
