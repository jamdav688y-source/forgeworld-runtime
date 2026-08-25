"""Mission-and-Evidence Envelope substrate.

Bounded, file-backed lifecycle tracking for missions moving through
BRONZE_RECEIVED -> SILVER_STRUCTURED -> GOLD_VALIDATED, with REJECTED and
QUARANTINED as explicit failure / malformed-input destinations.

Every stage transition is an append-only ledger event, written under a
per-mission, cross-process exclusive lock and durably committed via
write-temp-then-atomic-rename. A mission's record is a cached projection
of its ledger, never an independent source of truth -- reconstruct()
rebuilds the same record purely by replaying the ledger through the same
projection function the live path uses (_project_event).

Validation is not promotion: reaching GOLD_VALIDATED only means explicit
acceptance evidence was recorded. promotion_status only moves to PROMOTED
through record_promotion_authority(), which delegates entirely to an
injected AuthorityVerifier and fails closed -- with no verifier
configured, on rejection, on a malformed result, or on a result that does
not structurally name this exact mission and a promotion scope for it.
This module makes no judgment based on what a principal's name looks
like: it does not, and cannot, authenticate anyone. It only enforces the
external-verification interface and refuses to proceed without one.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only off POSIX
    fcntl = None

SCHEMA_VERSION = 1

BRONZE_RECEIVED = "BRONZE_RECEIVED"
SILVER_STRUCTURED = "SILVER_STRUCTURED"
GOLD_VALIDATED = "GOLD_VALIDATED"
REJECTED = "REJECTED"
QUARANTINED = "QUARANTINED"

LIFECYCLE_STAGES = (
    BRONZE_RECEIVED,
    SILVER_STRUCTURED,
    GOLD_VALIDATED,
    REJECTED,
    QUARANTINED,
)

NOT_PROMOTED = "NOT_PROMOTED"
PROMOTED = "PROMOTED"

_STRUCTURED_METADATA_FIELDS = (
    "cognitive_roles_required",
    "capabilities_required",
    "context_budget",
    "privacy_tier",
    "authority_tier",
)

MISSION_ID_MAX_LENGTH = 128
MISSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class EnvelopeError(Exception):
    """Base error for the mission-and-evidence envelope substrate."""


class InvalidMissionIdError(EnvelopeError):
    """mission_id failed the canonical validation contract."""


class MissionConflictError(EnvelopeError):
    """A mission_id already holds a different, non-replayed history."""


class InvalidTransitionError(EnvelopeError):
    """A transition was attempted from an incompatible lifecycle stage."""


class AcceptanceEvidenceMissingError(EnvelopeError):
    """GOLD_VALIDATED was attempted without explicit acceptance evidence."""


class AuthorityVerifierRequiredError(EnvelopeError):
    """No AuthorityVerifier is configured: EXTERNAL_AUTHORITY_VERIFIER_REQUIRED."""


class AuthorityVerificationRejectedError(EnvelopeError):
    """The configured AuthorityVerifier declined to authorize this request."""


class MalformedVerificationResultError(EnvelopeError):
    """The AuthorityVerifier's result did not structurally satisfy the contract."""


class AuthorityScopeError(EnvelopeError):
    """The verified authority_scope does not cover promotion of this mission."""


class MissingAttestationError(EnvelopeError):
    """The verified result carried no attestation_reference."""


class IntegrityError(EnvelopeError):
    """Base class for detected on-disk corruption."""


class SnapshotIntegrityError(IntegrityError):
    """A cached record snapshot is missing, unparsable, or malformed."""


class LedgerIntegrityError(IntegrityError):
    """A ledger file contains a malformed, partial, or unparsable line."""


class LockTimeoutError(EnvelopeError):
    """The per-mission writer lock could not be acquired in time."""


class UnsupportedPlatformError(EnvelopeError):
    """This platform lacks the POSIX primitive this substrate relies on."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _event_key(mission_id: str, transition: str, payload: Any) -> str:
    return sha256_bytes(
        _canonical({"mission_id": mission_id, "transition": transition, "payload": payload}).encode()
    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# REPAIR B: mission-id validation
# ---------------------------------------------------------------------------

def validate_mission_id(mission_id: Any) -> str:
    """Validate `mission_id` against the canonical, conservative contract.

    Never rewrites, trims, or otherwise "fixes" a hostile identifier -- it
    either returns the exact string it was given, unchanged, or raises
    InvalidMissionIdError. This is the single function every filesystem
    operation in EnvelopeStore funnels a mission_id through before it is
    used as any part of a path.
    """
    if not isinstance(mission_id, str):
        raise InvalidMissionIdError(f"mission_id must be a string, got {type(mission_id).__name__}")
    if mission_id == "":
        raise InvalidMissionIdError("mission_id must not be empty")
    if mission_id != mission_id.strip():
        raise InvalidMissionIdError("mission_id must not have leading or trailing whitespace")
    if len(mission_id) > MISSION_ID_MAX_LENGTH:
        raise InvalidMissionIdError(f"mission_id must be at most {MISSION_ID_MAX_LENGTH} characters")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in mission_id):
        raise InvalidMissionIdError("mission_id must not contain control characters")
    if ".." in mission_id:
        raise InvalidMissionIdError("mission_id must not contain '..'")
    if "/" in mission_id or "\\" in mission_id:
        raise InvalidMissionIdError("mission_id must not contain path separators")
    if unicodedata.normalize("NFC", mission_id) != mission_id:
        raise InvalidMissionIdError("mission_id must already be in normalized (NFC) form")
    if not MISSION_ID_PATTERN.match(mission_id):
        raise InvalidMissionIdError(
            "mission_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ "
            "(ASCII letters, digits, '.', '_', '-' only)"
        )
    return mission_id


# ---------------------------------------------------------------------------
# REPAIR A: external authority-verification interface
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuthorityVerificationRequest:
    """What EnvelopeStore asks an external AuthorityVerifier to check."""

    mission_id: str
    requested_scope: str
    statement: str


@dataclass(frozen=True)
class VerifiedAuthority:
    """A structured, non-secret attestation that a promotion is authorized.

    Deliberately shaped so it can never carry a credential: there is no
    field for a token, password, or key. attestation_reference points to
    *where* verification happened (an audit-log id, a ticket number, a
    signed-request id) -- never the secret material used to perform it.
    """

    principal_id: str
    authority_scope: Sequence[str]
    verification_method: str
    verified_at: str
    attestation_reference: str


class AuthorityVerifier(ABC):
    """External authority-verification boundary.

    EnvelopeStore never decides on its own whether a promotion is
    authorized, and it makes no judgment based on what a principal's name
    looks like. It delegates entirely to an injected AuthorityVerifier and
    fails closed if none is configured, if verification is rejected, or if
    the result does not structurally satisfy the required mission and
    scope. Implementing a real AuthorityVerifier backed by an actual
    identity provider or approval system is explicitly out of scope for
    this bounded substrate: this repository does not authenticate humans;
    it only defines and enforces the interface, and refuses to proceed
    without one.
    """

    @abstractmethod
    def verify(self, request: AuthorityVerificationRequest) -> Optional[VerifiedAuthority]:
        """Return a VerifiedAuthority if `request` is authorized, else None."""
        raise NotImplementedError


def _validate_verified_authority(result: Any, mission_id: str, required_scope: str) -> None:
    if not isinstance(result, VerifiedAuthority):
        raise MalformedVerificationResultError(
            f"verifier returned {type(result).__name__!r}, expected VerifiedAuthority"
        )
    if not isinstance(result.principal_id, str) or not result.principal_id.strip():
        raise MalformedVerificationResultError("principal_id is missing or empty")
    if not isinstance(result.verification_method, str) or not result.verification_method.strip():
        raise MalformedVerificationResultError("verification_method is missing or empty")
    if not isinstance(result.verified_at, str) or not _TIMESTAMP_PATTERN.match(result.verified_at):
        raise MalformedVerificationResultError(
            "verified_at is missing or not a recognizable timestamp (expected YYYY-MM-DDTHH:MM:SS...)"
        )
    if not isinstance(result.attestation_reference, str) or not result.attestation_reference.strip():
        raise MissingAttestationError("attestation_reference is missing or empty")

    scope = result.authority_scope
    if not isinstance(scope, (list, tuple, set, frozenset)) or not scope:
        raise MalformedVerificationResultError("authority_scope is missing or empty")
    if not all(isinstance(s, str) and s.strip() for s in scope):
        raise MalformedVerificationResultError("authority_scope must contain only non-empty strings")
    if required_scope not in scope:
        raise AuthorityScopeError(
            f"verified authority_scope {sorted(scope)!r} does not include required scope "
            f"{required_scope!r} for mission_id {mission_id!r}"
        )


# ---------------------------------------------------------------------------
# record projection (shared by the live write path and reconstruct())
# ---------------------------------------------------------------------------

def _new_record(mission_id: str, mission_version: Any) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "mission_version": mission_version,
        "lifecycle_stage": None,
        "source_artifacts": [],
        "content_hashes": {},
        "cognitive_roles_required": [],
        "capabilities_required": [],
        "context_budget": None,
        "privacy_tier": None,
        "authority_tier": None,
        "acceptance_tests": [],
        "execution_events": [],
        "evidence_artifacts": [],
        "promotion_status": NOT_PROMOTED,
        "unresolved_gaps": [],
        "promotion_authority": None,
    }


def _project_event(record: dict, event: dict) -> dict:
    """Fold one ledger event into a record. The only place stage logic
    lives -- used identically by the live write path and by reconstruct(),
    so replaying history can never diverge from what actually happened."""
    transition = event["transition"]
    detail = event.get("detail", {})

    if transition == "BRONZE_RECEIVED":
        record["mission_version"] = detail["mission_version"]
        record["lifecycle_stage"] = BRONZE_RECEIVED
        record["source_artifacts"] = detail["source_artifacts"]
        record["content_hashes"] = detail["content_hashes"]
        record["cognitive_roles_required"] = detail["cognitive_roles_required"]
        record["capabilities_required"] = detail["capabilities_required"]
        record["context_budget"] = detail["context_budget"]
        record["privacy_tier"] = detail["privacy_tier"]
        record["authority_tier"] = detail["authority_tier"]
    elif transition == "QUARANTINE":
        record["mission_version"] = detail["mission_version"]
        record["lifecycle_stage"] = QUARANTINED
        record["unresolved_gaps"] = record["unresolved_gaps"] + [detail["reason"]]
    elif transition == "SILVER_STRUCTURED":
        for field in _STRUCTURED_METADATA_FIELDS:
            if field in detail["structured_metadata"]:
                record[field] = detail["structured_metadata"][field]
        record["lifecycle_stage"] = SILVER_STRUCTURED
    elif transition == "VALIDATE_GOLD":
        record["acceptance_tests"] = detail["acceptance_tests"]
        record["evidence_artifacts"] = detail["evidence_artifacts"]
        record["lifecycle_stage"] = event["resulting_stage"]
        if event["resulting_stage"] == REJECTED:
            record["unresolved_gaps"] = record["unresolved_gaps"] + [
                f"acceptance test failed: {t.get('name', '?')}"
                for t in detail["acceptance_tests"]
                if not t.get("passed")
            ]
    elif transition == "REJECTED":
        record["lifecycle_stage"] = REJECTED
        record["unresolved_gaps"] = record["unresolved_gaps"] + [detail["reason"]]
    elif transition == "PROMOTION_AUTHORITY_RECORDED":
        record["promotion_status"] = PROMOTED
        record["promotion_authority"] = {**detail, "recorded_at": event["timestamp"]}
    else:
        raise EnvelopeError(f"unknown transition in ledger: {transition!r}")

    record["execution_events"] = record["execution_events"] + [event]
    return record


# ---------------------------------------------------------------------------
# REPAIR C: durable snapshot writes
# ---------------------------------------------------------------------------

def _fsync_directory(directory: Path) -> None:
    """Best-effort: fsync the containing directory so the atomic rename
    below is itself durable across a crash, not just the file contents.
    Not supported on all platforms/filesystems (notably Windows); failure
    here does not affect correctness, only crash-durability, so it is
    swallowed rather than raised."""
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` durably and atomically: write to a sibling
    temp file in the same directory, fsync it, then os.replace it into
    place, so a reader never observes a partially written file. On any
    failure before the replace, the temp file is removed and whatever was
    previously at `path` is left completely untouched."""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(directory))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    _fsync_directory(directory)


# ---------------------------------------------------------------------------
# REPAIR C: single-writer, cross-process ledger lock
# ---------------------------------------------------------------------------

class _FileLock:
    """POSIX advisory, cross-process exclusive lock via fcntl.flock on a
    dedicated per-mission lock file. Bounded: acquisition polls up to
    `timeout_seconds` and raises LockTimeoutError rather than blocking
    forever.

    The lock file itself is never deleted. Unlinking a lock file while
    another process still holds it open is a classic race: a third
    process can then create and lock a *new* inode at the same path, and
    the two "holders" silently stop excluding each other. This
    implementation only ever locks and unlocks the file; it never removes
    it, so an active writer's lock can never be deleted out from under it.

    Platform note: this relies on fcntl.flock, which is POSIX-only. Cross-
    process ledger-writer exclusion is therefore not supported on
    Windows; EnvelopeStore raises UnsupportedPlatformError there rather
    than silently falling back to a mechanism that would not actually be
    cross-process safe.
    """

    def __init__(self, path: Path, timeout_seconds: float, poll_interval: float = 0.02):
        if fcntl is None:
            raise UnsupportedPlatformError(
                "cross-process ledger locking requires POSIX fcntl.flock, "
                f"which is unavailable on {sys.platform!r}"
            )
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return self
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(fd)
                    raise
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise LockTimeoutError(
                        f"timed out after {self.timeout_seconds}s acquiring lock {self.path}"
                    )
                time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
        return False


class EnvelopeStore:
    """File-backed store for mission-and-evidence envelopes.

    Each mission gets a cached snapshot at records/<mission_id>.json,
    written atomically, and an append-only event ledger at
    ledger/<mission_id>.jsonl, written under a per-mission cross-process
    lock. `authority_verifier`, if given, is the sole source of truth for
    promotion authority; with none configured (the default), no mission
    can ever be promoted.
    """

    def __init__(
        self,
        root: Path,
        authority_verifier: Optional[AuthorityVerifier] = None,
        lock_timeout_seconds: float = 5.0,
    ):
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.ledger_dir = self.root / "ledger"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.authority_verifier = authority_verifier
        self.lock_timeout_seconds = lock_timeout_seconds

    # -- REPAIR B: path resolution never escapes the store root ---------
    def _resolve_within_root(self, name: str, base_dir: Path) -> Path:
        candidate = (base_dir / name).resolve()
        root_resolved = self.root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            raise InvalidMissionIdError(
                f"resolved path {candidate} escapes configured store root {root_resolved}"
            )
        return candidate

    def _record_path(self, mission_id: str) -> Path:
        return self._resolve_within_root(f"{mission_id}.json", self.records_dir)

    def _ledger_path(self, mission_id: str) -> Path:
        return self._resolve_within_root(f"{mission_id}.jsonl", self.ledger_dir)

    def _lock_path(self, mission_id: str) -> Path:
        return self._resolve_within_root(f"{mission_id}.lock", self.ledger_dir)

    # -- storage helpers -----------------------------------------------
    def _load(self, mission_id: str) -> Optional[dict]:
        path = self._record_path(mission_id)
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SnapshotIntegrityError(f"snapshot {path} could not be read: {exc}") from exc
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SnapshotIntegrityError(f"snapshot {path} is not valid JSON: {exc}") from exc
        if not isinstance(record, dict) or "execution_events" not in record or "mission_id" not in record:
            raise SnapshotIntegrityError(f"snapshot {path} is missing required record fields")
        return record

    def _atomic_save(self, record: dict) -> None:
        path = self._record_path(record["mission_id"])
        data = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
        _atomic_write_bytes(path, data)

    def _read_ledger(self, mission_id: str) -> list:
        path = self._ledger_path(mission_id)
        if not path.exists():
            return []
        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise LedgerIntegrityError(
                        f"ledger {path} line {line_number} is not newline-terminated "
                        "(truncated or partially written)"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerIntegrityError(
                        f"ledger {path} line {line_number} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(event, dict) or "transition" not in event or "event_key" not in event:
                    raise LedgerIntegrityError(
                        f"ledger {path} line {line_number} is missing required event fields"
                    )
                events.append(event)
        return events

    def _append_ledger_line(self, mission_id: str, event: dict) -> None:
        """Append one event. Caller must already hold this mission's lock."""
        line = (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
        with open(self._ledger_path(mission_id), "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def get(self, mission_id: str) -> Optional[dict]:
        mission_id = validate_mission_id(mission_id)
        return self._load(mission_id)

    def reconstruct(self, mission_id: str) -> Optional[dict]:
        """Rebuild a mission's record purely by replaying its ledger,
        independent of the cached snapshot."""
        mission_id = validate_mission_id(mission_id)
        events = self._read_ledger(mission_id)
        if not events:
            return None
        record = _new_record(mission_id, mission_version=None)
        for event in events:
            record = _project_event(record, event)
        return record

    # -- shared, lock-protected commit path -------------------------------
    def _commit(self, mission_id: str, build_event) -> dict:
        """Acquire this mission's single-writer, cross-process lock, then
        atomically: load the current record fresh, ask build_event(record)
        for the event to apply (it validates against live state and raises
        on any invalid transition), project it, durably append it to the
        ledger, and atomically snapshot the result. Idempotent: if the
        built event is identical to the last recorded one, nothing new is
        written and the existing record is returned unchanged."""
        lock_path = self._lock_path(mission_id)
        with _FileLock(lock_path, timeout_seconds=self.lock_timeout_seconds):
            record = self._load(mission_id)
            event = build_event(record)
            if record is not None and record["execution_events"]:
                if record["execution_events"][-1]["event_key"] == event["event_key"]:
                    return record  # identical replay: no new event, no duplicate
            record = _project_event(record if record is not None else _new_record(mission_id, None), event)
            self._append_ledger_line(mission_id, event)
            self._atomic_save(record)
            return record

    # -- transitions -------------------------------------------------------
    def receive_bronze(
        self,
        mission_id: str,
        mission_version: Any,
        source_artifacts: Optional[Iterable[str]],
        cognitive_roles_required: Iterable[str] = (),
        capabilities_required: Iterable[str] = (),
        context_budget: Any = None,
        privacy_tier: Any = None,
        authority_tier: Any = None,
    ) -> dict:
        mission_id = validate_mission_id(mission_id)

        malformed_reason = None
        if source_artifacts is None or isinstance(source_artifacts, (str, bytes)):
            malformed_reason = "source_artifacts must be a non-string iterable of paths"
            source_artifacts = []
        else:
            source_artifacts = list(source_artifacts)
            if not source_artifacts:
                malformed_reason = "source_artifacts is empty"

        if not mission_version:
            malformed_reason = malformed_reason or "mission_version is missing"

        if malformed_reason is not None:
            return self.quarantine(
                mission_id,
                mission_version,
                reason=malformed_reason,
                raw_input={"source_artifacts": source_artifacts},
            )

        missing = [a for a in source_artifacts if not Path(a).is_file()]
        if missing:
            return self.quarantine(
                mission_id,
                mission_version,
                reason=f"missing source artifact(s): {missing}",
                raw_input={"source_artifacts": source_artifacts},
            )

        content_hashes = {a: sha256_file(Path(a)) for a in source_artifacts}
        detail = {
            "mission_version": mission_version,
            "source_artifacts": source_artifacts,
            "content_hashes": content_hashes,
            "cognitive_roles_required": list(cognitive_roles_required),
            "capabilities_required": list(capabilities_required),
            "context_budget": context_budget,
            "privacy_tier": privacy_tier,
            "authority_tier": authority_tier,
        }
        key = _event_key(mission_id, "BRONZE_RECEIVED", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "BRONZE_RECEIVED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }

        def build_event(record: Optional[dict]) -> dict:
            if record is not None and record["lifecycle_stage"] is not None:
                already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
                if not already:
                    raise MissionConflictError(
                        f"mission_id {mission_id!r} already has stage {record['lifecycle_stage']!r}; "
                        "cannot re-receive as BRONZE with different content"
                    )
            return event

        return self._commit(mission_id, build_event)

    def quarantine(
        self, mission_id: str, mission_version: Any, reason: str, raw_input: Any = None
    ) -> dict:
        mission_id = validate_mission_id(mission_id)
        detail = {"mission_version": mission_version, "reason": reason, "raw_input": raw_input}
        key = _event_key(mission_id, "QUARANTINE", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "QUARANTINE",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }

        def build_event(record: Optional[dict]) -> dict:
            return event

        return self._commit(mission_id, build_event)

    def structure_silver(self, mission_id: str, structured_metadata: dict) -> dict:
        mission_id = validate_mission_id(mission_id)
        detail = {"structured_metadata": structured_metadata}
        key = _event_key(mission_id, "SILVER_STRUCTURED", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "SILVER_STRUCTURED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }

        def build_event(record: Optional[dict]) -> dict:
            if record is None:
                raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
            already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
            if not already and record["lifecycle_stage"] != BRONZE_RECEIVED:
                raise InvalidTransitionError(
                    f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                    f"{SILVER_STRUCTURED} requires {BRONZE_RECEIVED}"
                )
            return event

        return self._commit(mission_id, build_event)

    def validate_gold(
        self, mission_id: str, acceptance_tests: list, evidence_artifacts: list
    ) -> dict:
        mission_id = validate_mission_id(mission_id)
        detail = {"acceptance_tests": acceptance_tests, "evidence_artifacts": evidence_artifacts}
        key = _event_key(mission_id, "VALIDATE_GOLD", detail)
        resulting_stage = (
            GOLD_VALIDATED
            if acceptance_tests and all(bool(t.get("passed")) for t in acceptance_tests)
            else REJECTED
        )
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "VALIDATE_GOLD",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
            "resulting_stage": resulting_stage,
        }

        def build_event(record: Optional[dict]) -> dict:
            if record is None:
                raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
            already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
            if not already:
                if record["lifecycle_stage"] != SILVER_STRUCTURED:
                    raise InvalidTransitionError(
                        f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                        f"{GOLD_VALIDATED} requires {SILVER_STRUCTURED}"
                    )
                if not acceptance_tests or not evidence_artifacts:
                    raise AcceptanceEvidenceMissingError(
                        f"mission {mission_id!r} cannot enter {GOLD_VALIDATED} without explicit "
                        "acceptance_tests and evidence_artifacts"
                    )
            return event

        return self._commit(mission_id, build_event)

    def reject(self, mission_id: str, reason: str) -> dict:
        mission_id = validate_mission_id(mission_id)
        detail = {"reason": reason}
        key = _event_key(mission_id, "REJECTED", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "REJECTED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }

        def build_event(record: Optional[dict]) -> dict:
            if record is None:
                raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
            already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
            if not already and record["lifecycle_stage"] not in (BRONZE_RECEIVED, SILVER_STRUCTURED):
                raise InvalidTransitionError(
                    f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                    f"{REJECTED} is only reachable from {BRONZE_RECEIVED} or {SILVER_STRUCTURED}"
                )
            return event

        return self._commit(mission_id, build_event)

    def record_promotion_authority(self, mission_id: str, statement: str) -> dict:
        """Record promotion authority for `mission_id`.

        This never inspects any actor name to decide anything -- it has no
        opinion on what a "human-looking" or "machine-looking" identifier
        is. The only thing that can authorize a promotion is a
        VerifiedAuthority returned by the injected AuthorityVerifier, and
        that result must structurally name this exact mission and a
        promotion scope for it. Every other outcome -- no verifier
        configured, an explicit rejection, a malformed result, the wrong
        scope, a result naming a different mission, or a missing
        attestation -- fails closed.
        """
        mission_id = validate_mission_id(mission_id)

        if self.authority_verifier is None:
            raise AuthorityVerifierRequiredError(
                "EXTERNAL_AUTHORITY_VERIFIER_REQUIRED: no AuthorityVerifier is configured on this "
                "EnvelopeStore; promotion authority cannot be recorded without one."
            )

        required_scope = f"promote:{mission_id}"
        request = AuthorityVerificationRequest(
            mission_id=mission_id, requested_scope=required_scope, statement=statement
        )
        result = self.authority_verifier.verify(request)
        if result is None:
            raise AuthorityVerificationRejectedError(
                f"authority verification was rejected for mission_id {mission_id!r}"
            )
        _validate_verified_authority(result, mission_id, required_scope)

        detail = {
            "principal_id": result.principal_id,
            "authority_scope": list(result.authority_scope),
            "verification_method": result.verification_method,
            "verified_at": result.verified_at,
            "attestation_reference": result.attestation_reference,
            "statement": statement,
        }
        key = _event_key(mission_id, "PROMOTION_AUTHORITY_RECORDED", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "PROMOTION_AUTHORITY_RECORDED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }

        def build_event(record: Optional[dict]) -> dict:
            if record is None:
                raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
            already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
            if not already and record["lifecycle_stage"] != GOLD_VALIDATED:
                raise InvalidTransitionError(
                    f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                    f"promotion requires {GOLD_VALIDATED}"
                )
            return event

        return self._commit(mission_id, build_event)
