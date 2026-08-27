"""Mission-and-Evidence Envelope substrate.

Bounded, file-backed lifecycle tracking for missions moving through
BRONZE_RECEIVED -> SILVER_STRUCTURED -> GOLD_VALIDATED, with REJECTED and
QUARANTINED as explicit failure / malformed-input destinations.

DURABILITY LAW (the reason this file is structured the way it is):

    THE APPEND-ONLY EVENT HISTORY IS AUTHORITATIVE.
    THE SNAPSHOT IS A DERIVED, REBUILDABLE PROJECTION.
    SNAPSHOT FAILURE MUST NEVER ERASE, DUPLICATE OR CONTRADICT A
    COMMITTED EVENT.

Every mutation goes through EnvelopeStore._commit(), which, under a
per-mission cross-process lock: reads and validates the *complete*
ledger, reconstructs current state from it, validates and idempotency-
checks the proposed transition purely against that reconstruction (never
against the cached snapshot), and then has exactly one commit point --
atomically replacing the whole ledger file with its old contents plus the
one new event. Everything before that replace is uncommitted and has no
effect if interrupted; everything after it is durably committed, even if
the snapshot write that follows fails. The snapshot is always rebuilt
from -- and, on every read, verified against -- the ledger; a missing,
stale, or corrupted snapshot is silently self-healing. A corrupted
*ledger* is not: it fails closed with a distinguishable integrity error,
and no transition is attempted while that error stands.

Validation is not promotion: reaching GOLD_VALIDATED only means explicit
acceptance evidence was recorded. record_promotion_authority() records a
verified, append-only attestation that a named principal has been
granted promotion scope for this exact mission -- but, deliberately and
conservatively, does not itself flip promotion_status. This bounded
increment does not implement an actual promotion action, only the
evidentiary record that a human authority verified and attested to one;
an actual promotion (or a future revocation) would need its own,
separately governed, append-only event type, which is out of scope here.
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
from typing import Any, Callable, Iterable, Optional, Sequence

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
# PROMOTED is intentionally unreachable in this bounded increment: per
# Phase 7's conservative resolution, recording a verified promotion
# attestation does not itself promote anything. It is kept defined (not
# deleted) as the documented target state a future, separately governed
# promotion event type would set.
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


class IdempotencyConflictError(EnvelopeError):
    """A ledger event with this identifier already exists with different content."""


class AuthorityConflictError(IdempotencyConflictError):
    """A different, already-recorded promotion attestation exists for this mission.

    Promotion-authority attestations are append-only in this substrate:
    the exact same verified attestation may be recorded again (idempotent
    no-op), but a *different* principal, scope, mission, method, or
    attestation_reference is refused outright -- AUTHORITY_CONFLICT.
    Revocation or replacement is not implemented in this increment; it
    would need its own, separately governed, append-only event type.
    """


class LedgerIntegrityError(EnvelopeError):
    """LEDGER_INTEGRITY_ERROR: the authoritative ledger is malformed, partial,
    or unparsable. Never silently skipped, and never recovered from the
    snapshot -- the ledger is authoritative, so its own corruption fails
    closed."""


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
# mission-id validation (from FW-REPAIR-EVIDENCE-ENVELOPE-001)
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
# external authority-verification interface (from FW-REPAIR-EVIDENCE-ENVELOPE-001)
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
# record projection (shared by the live write path, reads, and reconstruct())
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
    lives -- used identically by the write path, reads, and reconstruct(),
    so no path can ever diverge from what the ledger actually says."""
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
        # Deliberately does NOT set promotion_status. See Phase 7 / module
        # docstring: recording a verified attestation is not itself a
        # promotion. promotion_authority becomes the visible evidence that
        # a human authority verified and attested to promoting this
        # mission; an actual promotion is a separate, not-yet-implemented
        # action.
        record["promotion_authority"] = {**detail, "recorded_at": event["timestamp"]}
    else:
        raise EnvelopeError(f"unknown transition in ledger: {transition!r}")

    record["execution_events"] = record["execution_events"] + [event]
    return record


# ---------------------------------------------------------------------------
# durable, atomic single-file writes (ledger replacement and snapshot cache)
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
    failure before the replace, the temp file this call itself created is
    removed (ownership is proven by construction: it is always this
    call's own freshly minted tempfile.mkstemp() path, never anything
    discovered by scanning the directory) and whatever was previously at
    `path` is left completely untouched."""
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


def _ledger_content_hash(events: list) -> str:
    """A deterministic fingerprint of an exact, ordered event history."""
    return sha256_bytes(_canonical([e["event_key"] for e in events]).encode())


def _serialize_ledger(events: list) -> bytes:
    return b"".join((json.dumps(e, sort_keys=True) + "\n").encode("utf-8") for e in events)


# ---------------------------------------------------------------------------
# single-writer, cross-process lock
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
    process writer exclusion is therefore not supported on Windows;
    EnvelopeStore raises UnsupportedPlatformError there rather than
    silently falling back to a mechanism that would not actually be
    cross-process safe.
    """

    def __init__(self, path: Path, timeout_seconds: float, poll_interval: float = 0.02):
        if fcntl is None:
            raise UnsupportedPlatformError(
                "cross-process locking requires POSIX fcntl.flock, "
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


def _default_fault_hook(point: str) -> None:
    return None


class EnvelopeStore:
    """File-backed store for mission-and-evidence envelopes.

    The ledger at ledger/<mission_id>.jsonl is authoritative: every read
    validates it and reconstructs current state from it. The snapshot at
    records/<mission_id>.json is a derived cache carrying projection
    metadata (last_event_id, event_count, a ledger content fingerprint,
    schema_version) alongside the reconstructed record; it is compared
    against a fresh ledger reconstruction on every read and silently
    self-heals when missing, stale, or corrupted. Both files are written
    via write-temp-then-atomic-rename, and every mutation is serialized
    per mission_id via a cross-process advisory lock.

    `authority_verifier`, if given, is the sole source of truth for
    promotion-authority verification; with none configured (the
    default), no attestation can ever be recorded.

    `_fault_hook`, if given, is called at three points inside _commit
    ("before_ledger_replace", "after_ledger_replace_before_snapshot",
    "after_snapshot_replace") purely so tests can deterministically
    simulate a failure at an exact commit boundary without timing-
    dependent sleeps or killing real processes. It is a no-op by default
    and is not part of the public contract -- production code must never
    pass anything but the default.
    """

    def __init__(
        self,
        root: Path,
        authority_verifier: Optional[AuthorityVerifier] = None,
        lock_timeout_seconds: float = 5.0,
        _fault_hook: Optional[Callable[[str], None]] = None,
    ):
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.ledger_dir = self.root / "ledger"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.authority_verifier = authority_verifier
        self.lock_timeout_seconds = lock_timeout_seconds
        self._fault_hook = _fault_hook or _default_fault_hook

    # -- path resolution never escapes the store root -------------------
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

    # -- authoritative ledger: read + validate --------------------------
    def _read_ledger(self, mission_id: str) -> list:
        """Read and validate the complete ledger. Raises LedgerIntegrityError
        (never a bare parse exception, never a silent skip) on any partial
        or malformed line -- this is the sole fail-closed gate for
        authoritative history corruption."""
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

    def _reconstruct_from_events(self, mission_id: str, events: list) -> Optional[dict]:
        if not events:
            return None
        record = _new_record(mission_id, mission_version=None)
        for event in events:
            record = _project_event(record, event)
        return record

    def _atomic_replace_ledger(self, mission_id: str, events: list) -> None:
        """THE single commit point. Atomically replaces the mission's
        entire ledger file with `events` serialized as complete JSONL.
        Before this call returns successfully, none of `events` is
        committed; after it returns successfully, all of them are -- even
        if the derived snapshot projection that follows fails.

        The physical file is replaced as a whole rather than appended to,
        so a reader can never observe a partially written trailing line,
        and the write is always of a complete, freshly-validated event
        list (built from a validated read), so an existing event can
        never be silently discarded, reordered, or duplicated by this
        call. This whole-file-replace approach is appropriate for this
        bounded, small, single-mission-per-file local substrate; it is
        not a design suited to an unbounded production ledger, where
        rewriting the entire history on every event would not scale --
        that would need a genuine write-ahead log or a segmented/
        compacted ledger instead.
        """
        self._atomic_replace_ledger_bytes(mission_id, _serialize_ledger(events))

    def _atomic_replace_ledger_bytes(self, mission_id: str, data: bytes) -> None:
        _atomic_write_bytes(self._ledger_path(mission_id), data)

    # -- derived snapshot cache: metadata, load, write, staleness --------
    def _projection_metadata(self, mission_id: str, events: list) -> dict:
        return {
            "mission_id": mission_id,
            "last_event_id": events[-1]["event_id"] if events else None,
            "event_count": len(events),
            "ledger_content_hash": _ledger_content_hash(events),
            "schema_version": SCHEMA_VERSION,
        }

    def _load_snapshot_wrapper(self, mission_id: str) -> Optional[dict]:
        """Load the cached snapshot wrapper. Any problem reading or
        parsing it (missing, corrupted, truncated, wrong shape) is
        treated as "absent" rather than raised: unlike the ledger, the
        snapshot is a rebuildable derived cache, so its own corruption is
        never fatal -- callers simply rebuild it from the ledger."""
        path = self._record_path(mission_id)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(wrapper, dict) or "record" not in wrapper or "projection_metadata" not in wrapper:
            return None
        return wrapper

    def _write_derived_snapshot(self, mission_id: str, events: list, record: dict) -> None:
        wrapper = {
            "projection_metadata": self._projection_metadata(mission_id, events),
            "record": record,
        }
        data = json.dumps(wrapper, indent=2, sort_keys=True).encode("utf-8")
        _atomic_write_bytes(self._record_path(mission_id), data)

    # -- public reads ------------------------------------------------------
    def get(self, mission_id: str) -> Optional[dict]:
        """Return this mission's current state, always reconstructed from
        and verified against the authoritative ledger. The cached
        snapshot is consulted only as a hint and is never trusted: it is
        compared against a fresh reconstruction and opportunistically
        repaired in place (atomically) whenever it is missing, stale, or
        inconsistent. Fails closed (LedgerIntegrityError) if the ledger
        itself is corrupt; never falls back to snapshot content in that
        case."""
        mission_id = validate_mission_id(mission_id)
        events = self._read_ledger(mission_id)
        record = self._reconstruct_from_events(mission_id, events)
        if record is None:
            return None

        expected_meta = self._projection_metadata(mission_id, events)
        wrapper = self._load_snapshot_wrapper(mission_id)
        stale = (
            wrapper is None
            or wrapper.get("projection_metadata") != expected_meta
            or wrapper.get("record") != record
        )
        if stale:
            try:
                self._write_derived_snapshot(mission_id, events, record)
            except OSError:
                pass  # best-effort repair; the correct data is still returned below
        return record

    def reconstruct(self, mission_id: str) -> Optional[dict]:
        """Rebuild a mission's record purely by replaying its ledger --
        the same authoritative source get() verifies against, exposed
        directly with zero snapshot interaction (no read, no write)."""
        mission_id = validate_mission_id(mission_id)
        events = self._read_ledger(mission_id)
        return self._reconstruct_from_events(mission_id, events)

    # -- shared, lock-protected commit path -------------------------------
    def _commit(self, mission_id: str, make_event: Callable[[Optional[dict], list], dict]) -> dict:
        """Acquire this mission's single-writer, cross-process lock, then:

          1. Read and validate the complete authoritative ledger.
          2. Reconstruct current state from it.
          3/5. Call make_event(record, events), which validates the
               proposed transition against that reconstruction and
               determines idempotency from the ledger itself (never the
               snapshot), returning the event to apply -- or raising.
          6/7. Build the complete next ledger and commit it atomically.
               This is the one commit point: before it returns, nothing
               is committed; after, the event is committed regardless of
               what happens next.
          8/9. Re-read the newly committed ledger (proving what is
               actually durable, not just what was computed in memory),
               reconstruct from it, and write the derived snapshot.
         10.   (lock released by the `with` block on any exit, including
               an exception from any of the above.)
        """
        lock_path = self._lock_path(mission_id)
        with _FileLock(lock_path, timeout_seconds=self.lock_timeout_seconds):
            events = self._read_ledger(mission_id)
            record = self._reconstruct_from_events(mission_id, events)
            event = make_event(record, events)

            if any(e["event_key"] == event["event_key"] for e in events):
                return record  # identical event already committed: idempotent no-op

            self._fault_hook("before_ledger_replace")
            self._atomic_replace_ledger(mission_id, events + [event])
            self._fault_hook("after_ledger_replace_before_snapshot")

            committed_events = self._read_ledger(mission_id)
            committed_record = self._reconstruct_from_events(mission_id, committed_events)
            self._write_derived_snapshot(mission_id, committed_events, committed_record)
            self._fault_hook("after_snapshot_replace")
            return committed_record

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

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already and record is not None and record["lifecycle_stage"] is not None:
                raise MissionConflictError(
                    f"mission_id {mission_id!r} already has stage {record['lifecycle_stage']!r}; "
                    "cannot re-receive as BRONZE with different content"
                )
            return event

        return self._commit(mission_id, make_event)

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

        def make_event(record: Optional[dict], events: list) -> dict:
            return event

        return self._commit(mission_id, make_event)

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

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already:
                if record is None:
                    raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
                if record["lifecycle_stage"] != BRONZE_RECEIVED:
                    raise InvalidTransitionError(
                        f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                        f"{SILVER_STRUCTURED} requires {BRONZE_RECEIVED}"
                    )
            return event

        return self._commit(mission_id, make_event)

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

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already:
                if record is None:
                    raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
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

        return self._commit(mission_id, make_event)

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

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already:
                if record is None:
                    raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
                if record["lifecycle_stage"] not in (BRONZE_RECEIVED, SILVER_STRUCTURED):
                    raise InvalidTransitionError(
                        f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                        f"{REJECTED} is only reachable from {BRONZE_RECEIVED} or {SILVER_STRUCTURED}"
                    )
            return event

        return self._commit(mission_id, make_event)

    def record_promotion_authority(self, mission_id: str, statement: str) -> dict:
        """Record a verified, append-only promotion-authority attestation
        for `mission_id`.

        This never inspects any actor name to decide anything -- it has no
        opinion on what a "human-looking" or "machine-looking" identifier
        is. The only thing that can produce an attestation is a
        VerifiedAuthority returned by the injected AuthorityVerifier, and
        that result must structurally name this exact mission and a
        promotion scope for it. Every other outcome -- no verifier
        configured, an explicit rejection, a malformed result, the wrong
        scope, a result naming a different mission, or a missing
        attestation -- fails closed.

        Once an attestation is recorded, it is immutable: recording the
        exact same one again is an idempotent no-op; attempting to record
        a *different* one for the same mission raises AuthorityConflictError
        (AUTHORITY_CONFLICT). There is no revocation or replacement in
        this increment.

        Deliberately does not itself change promotion_status -- see the
        module docstring and Phase 7.
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

        def make_event(record: Optional[dict], events: list) -> dict:
            existing = next(
                (e for e in events if e["transition"] == "PROMOTION_AUTHORITY_RECORDED"), None
            )
            if existing is not None:
                if existing["event_key"] != key:
                    raise AuthorityConflictError(
                        f"mission {mission_id!r} already has a different recorded promotion "
                        "attestation; promotion authority is append-only and cannot be replaced "
                        "in this increment (AUTHORITY_CONFLICT)"
                    )
                return event  # identical attestation replayed: idempotent, handled by _commit
            if record is None:
                raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")
            if record["lifecycle_stage"] != GOLD_VALIDATED:
                raise InvalidTransitionError(
                    f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                    f"promotion requires {GOLD_VALIDATED}"
                )
            return event

        return self._commit(mission_id, make_event)
