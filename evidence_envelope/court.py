"""Constitutional Court state-transition graph, built on top of the
mission-and-evidence envelope substrate (envelope.py) rather than
duplicating it.

DISCOVERED ARCHITECTURE (FW-CONSTITUTIONAL-COURT-STATE-GRAPH-001): before
this module, no "Constitutional Court," admissibility ruling, appeal, or
terminal-state graph existed anywhere in this repository -- not in code,
schemas, tests, logs, or governance text. envelope.py's EnvelopeStore is
the only code-backed, tested, fail-closed, append-only ledger substrate
that exists. Per the architecture freeze, this module does not invent a
new runtime, registry, or control plane: it reuses envelope.py's proven
primitives directly --
    envelope.validate_mission_id()   for the identical, conservative
                                      identifier contract (used here for
                                      case_id)
    envelope._FileLock               for per-case, cross-process,
                                      single-writer exclusion
    envelope._atomic_write_bytes()   for durable, atomic ledger/snapshot
                                      writes
    envelope._serialize_ledger() / envelope._event_key() /
    envelope._ledger_content_hash()  for canonical serialization and
                                      deterministic event/ledger hashing
    envelope.AuthorityVerifier / AuthorityVerificationRequest /
    VerifiedAuthority                as the identical external
                                      authority-verification boundary
    envelope.LedgerIntegrityError / InvalidTransitionError /
    AuthorityVerifier*Error / AcceptanceEvidenceMissingError /
    AuthorityConflictError           reused directly: these are generic
                                      failure modes, not mission-specific
                                      ones

CourtStore does NOT subclass EnvelopeStore: EnvelopeStore's own
_project_event()/_new_record() and its transition methods (receive_bronze,
structure_silver, validate_gold, ...) are hardcoded to the mission
BRONZE/SILVER/GOLD lifecycle and cannot represent a case's admissibility
and adjudication stages. CourtStore instead has the same *shape*
(_record_path/_ledger_path/_lock_path/_commit/get/reconstruct) keyed by
case_id, with its own record projection, wired to the same shared, already
-tested storage primitives.

CASE STATE GRAPH:

    FILED -> ADMITTED -> APPROVED
                       -> REJECTED
    FILED -> INADMISSIBLE               (admissibility ruling failed)
    (FILED | ADMITTED) -> QUARANTINED   (malformed/corrupt case discovered)

APPROVED, REJECTED, INADMISSIBLE, and QUARANTINED are explicit terminal
states: unlike envelope.py's quarantine() (which does not gate on the
current lifecycle stage at all), every transition in this module
-- including quarantine_case() -- fails closed with InvalidTransitionError
against a case already in a terminal stage. This is a deliberate,
stricter choice made for the Court (FW-CONSTITUTIONAL-COURT-STATE-GRAPH-001
decision #3): a closed case's ledger is never reopened.

APPEAL is never a reopening of a closed ledger. It is representable only
as filing a brand-new case whose `appeal_of` cites the exact case_id and
ledger content hash of the terminal case it appeals -- file_case()
verifies that referenced case is terminal and that the cited hash matches
its *current* ledger exactly (replay/stale-state protection), then never
touches that ledger again.

DECIDE (the adjudication itself) requires a real, externally verified
AuthorityVerifier result naming this exact case_id and an "adjudicate:"
scope -- there is no code path by which narrative text (e.g. a
council_reviews/council.log-style entry) can satisfy this. This differs
from envelope.py's record_promotion_authority(), which deliberately
records a verified attestation WITHOUT flipping promotion_status (Phase 7
left the actual promotion action out of scope). For the Court, the
verified decision *is* the governed action: once authority is verified,
decide() commits the terminal ruling in the same event.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

import envelope

SCHEMA_VERSION = 1

FILED = "FILED"
ADMITTED = "ADMITTED"
INADMISSIBLE = "INADMISSIBLE"
QUARANTINED = "QUARANTINED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"

CASE_STAGES = (FILED, ADMITTED, INADMISSIBLE, QUARANTINED, APPROVED, REJECTED)
TERMINAL_STAGES = (INADMISSIBLE, QUARANTINED, APPROVED, REJECTED)

_RULINGS = (APPROVED, REJECTED)


class CaseConflictError(envelope.EnvelopeError):
    """A case_id already holds a different, non-replayed history."""


class InvalidAppealReferenceError(envelope.EnvelopeError):
    """An appeal's `appeal_of` reference does not name a real, terminal,
    exactly-matching prior case."""


def _validate_verified_authority_for_case(result: Any, case_id: str, required_scope: str) -> None:
    """Structurally identical to envelope._validate_verified_authority(),
    reimplemented (not imported) only so failure messages correctly say
    "case_id" instead of the mission-specific wording baked into that
    function's own error strings. The validation contract itself --
    which fields must be present, and that authority_scope must include
    required_scope -- is not duplicated logic in any meaningful sense; it
    is the same three-line structural check envelope.py already performs.
    """
    if not isinstance(result, envelope.VerifiedAuthority):
        raise envelope.MalformedVerificationResultError(
            f"verifier returned {type(result).__name__!r}, expected VerifiedAuthority"
        )
    if not isinstance(result.principal_id, str) or not result.principal_id.strip():
        raise envelope.MalformedVerificationResultError("principal_id is missing or empty")
    if not isinstance(result.verification_method, str) or not result.verification_method.strip():
        raise envelope.MalformedVerificationResultError("verification_method is missing or empty")
    if not isinstance(result.verified_at, str) or not envelope._TIMESTAMP_PATTERN.match(result.verified_at):
        raise envelope.MalformedVerificationResultError(
            "verified_at is missing or not a recognizable timestamp (expected YYYY-MM-DDTHH:MM:SS...)"
        )
    if not isinstance(result.attestation_reference, str) or not result.attestation_reference.strip():
        raise envelope.MissingAttestationError("attestation_reference is missing or empty")

    scope = result.authority_scope
    if not isinstance(scope, (list, tuple, set, frozenset)) or not scope:
        raise envelope.MalformedVerificationResultError("authority_scope is missing or empty")
    if not all(isinstance(s, str) and s.strip() for s in scope):
        raise envelope.MalformedVerificationResultError("authority_scope must contain only non-empty strings")
    if required_scope not in scope:
        raise envelope.AuthorityScopeError(
            f"verified authority_scope {sorted(scope)!r} does not include required scope "
            f"{required_scope!r} for case_id {case_id!r}"
        )


def _new_case_record(case_id: str, case_version: Any) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "case_version": case_version,
        "case_stage": None,
        "claim": None,
        "source_artifacts": [],
        "content_hashes": {},
        "requested_relief": None,
        "appeal_of": None,
        "admissibility_checks": [],
        "ruling": None,
        "decision_evidence": [],
        "rationale": None,
        "decision_authority": None,
        "unresolved_gaps": [],
        "execution_events": [],
    }


def _project_case_event(record: dict, event: dict) -> dict:
    """The only place case-stage logic lives -- used identically by the
    write path, reads, and reconstruct(), mirroring envelope._project_event.
    """
    transition = event["transition"]
    detail = event.get("detail", {})

    if transition == "FILED":
        record["case_version"] = detail["case_version"]
        record["case_stage"] = FILED
        record["claim"] = detail["claim"]
        record["source_artifacts"] = detail["source_artifacts"]
        record["content_hashes"] = detail["content_hashes"]
        record["requested_relief"] = detail["requested_relief"]
        record["appeal_of"] = detail["appeal_of"]
    elif transition == "QUARANTINE":
        record["case_version"] = detail["case_version"]
        record["case_stage"] = QUARANTINED
        record["unresolved_gaps"] = record["unresolved_gaps"] + [detail["reason"]]
    elif transition == "ADMISSIBILITY_RULED":
        record["admissibility_checks"] = detail["evidence_sufficiency_checks"]
        record["case_stage"] = event["resulting_stage"]
        if event["resulting_stage"] == INADMISSIBLE:
            record["unresolved_gaps"] = record["unresolved_gaps"] + [
                f"admissibility check failed: {c.get('name', '?')}"
                for c in detail["evidence_sufficiency_checks"]
                if not c.get("passed")
            ]
    elif transition == "DECIDED":
        record["ruling"] = detail["ruling"]
        record["decision_evidence"] = detail["decision_evidence"]
        record["rationale"] = detail["rationale"]
        record["decision_authority"] = {
            "principal_id": detail["principal_id"],
            "authority_scope": detail["authority_scope"],
            "verification_method": detail["verification_method"],
            "verified_at": detail["verified_at"],
            "attestation_reference": detail["attestation_reference"],
            "statement": detail["statement"],
            "recorded_at": event["timestamp"],
        }
        record["case_stage"] = event["resulting_stage"]
    else:
        raise envelope.EnvelopeError(f"unknown transition in ledger: {transition!r}")

    record["execution_events"] = record["execution_events"] + [event]
    return record


class CourtStore:
    """File-backed store for Constitutional Court cases.

    Same durability law as EnvelopeStore: the ledger at
    ledger/<case_id>.jsonl is authoritative; the snapshot at
    records/<case_id>.json is a derived, self-healing projection. Every
    mutation is serialized per case_id via a cross-process advisory lock
    (envelope._FileLock) and committed with exactly one atomic whole-file
    replace (envelope._atomic_write_bytes), reused unmodified from
    envelope.py.

    `authority_verifier`, if given, is the sole source of truth for
    adjudication authority; with none configured (the default), decide()
    always fails closed.
    """

    def __init__(
        self,
        root: Path,
        authority_verifier: Optional[envelope.AuthorityVerifier] = None,
        lock_timeout_seconds: float = 5.0,
    ):
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.ledger_dir = self.root / "ledger"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.authority_verifier = authority_verifier
        self.lock_timeout_seconds = lock_timeout_seconds

    # -- path resolution never escapes the store root -------------------
    def _resolve_within_root(self, name: str, base_dir: Path) -> Path:
        candidate = (base_dir / name).resolve()
        root_resolved = self.root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            raise envelope.InvalidMissionIdError(
                f"resolved path {candidate} escapes configured store root {root_resolved}"
            )
        return candidate

    def _record_path(self, case_id: str) -> Path:
        return self._resolve_within_root(f"{case_id}.json", self.records_dir)

    def _ledger_path(self, case_id: str) -> Path:
        return self._resolve_within_root(f"{case_id}.jsonl", self.ledger_dir)

    def _lock_path(self, case_id: str) -> Path:
        return self._resolve_within_root(f"{case_id}.lock", self.ledger_dir)

    # -- authoritative ledger: read + validate --------------------------
    def _read_ledger(self, case_id: str) -> list:
        """Delegates to envelope's fail-closed line-by-line ledger reader
        so a corrupted Court ledger fails exactly the same way a
        corrupted mission ledger does: LedgerIntegrityError, never a
        silent skip, never a bare parse exception."""
        path = self._ledger_path(case_id)
        if not path.exists():
            return []
        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(
                        f"ledger {path} line {line_number} is not newline-terminated "
                        "(truncated or partially written)"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise envelope.LedgerIntegrityError(
                        f"ledger {path} line {line_number} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(event, dict) or "transition" not in event or "event_key" not in event:
                    raise envelope.LedgerIntegrityError(
                        f"ledger {path} line {line_number} is missing required event fields"
                    )
                events.append(event)
        return events

    def _reconstruct_from_events(self, case_id: str, events: list) -> Optional[dict]:
        if not events:
            return None
        record = _new_case_record(case_id, case_version=None)
        for event in events:
            record = _project_case_event(record, event)
        return record

    def _projection_metadata(self, case_id: str, events: list) -> dict:
        return {
            "case_id": case_id,
            "last_event_id": events[-1]["event_id"] if events else None,
            "event_count": len(events),
            "ledger_content_hash": envelope._ledger_content_hash(events),
            "schema_version": SCHEMA_VERSION,
        }

    def _load_snapshot_wrapper(self, case_id: str) -> Optional[dict]:
        path = self._record_path(case_id)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(wrapper, dict) or "record" not in wrapper or "projection_metadata" not in wrapper:
            return None
        return wrapper

    def _write_derived_snapshot(self, case_id: str, events: list, record: dict) -> None:
        wrapper = {
            "projection_metadata": self._projection_metadata(case_id, events),
            "record": record,
        }
        data = json.dumps(wrapper, indent=2, sort_keys=True).encode("utf-8")
        envelope._atomic_write_bytes(self._record_path(case_id), data)

    # -- public reads ------------------------------------------------------
    def get(self, case_id: str) -> Optional[dict]:
        """Always reconstructed from and verified against the
        authoritative ledger; fails closed (LedgerIntegrityError) if the
        ledger itself is corrupt."""
        case_id = envelope.validate_mission_id(case_id)
        events = self._read_ledger(case_id)
        record = self._reconstruct_from_events(case_id, events)
        if record is None:
            return None

        expected_meta = self._projection_metadata(case_id, events)
        wrapper = self._load_snapshot_wrapper(case_id)
        stale = (
            wrapper is None
            or wrapper.get("projection_metadata") != expected_meta
            or wrapper.get("record") != record
        )
        if stale:
            try:
                self._write_derived_snapshot(case_id, events, record)
            except OSError:
                pass
        return record

    def reconstruct(self, case_id: str) -> Optional[dict]:
        case_id = envelope.validate_mission_id(case_id)
        events = self._read_ledger(case_id)
        return self._reconstruct_from_events(case_id, events)

    # -- shared, lock-protected commit path -------------------------------
    def _commit(self, case_id, make_event) -> dict:
        lock_path = self._lock_path(case_id)
        with envelope._FileLock(lock_path, timeout_seconds=self.lock_timeout_seconds):
            events = self._read_ledger(case_id)
            record = self._reconstruct_from_events(case_id, events)
            event = make_event(record, events)

            if any(e["event_key"] == event["event_key"] for e in events):
                return record  # identical event already committed: idempotent no-op

            envelope._atomic_write_bytes(self._ledger_path(case_id), envelope._serialize_ledger(events + [event]))

            committed_events = self._read_ledger(case_id)
            committed_record = self._reconstruct_from_events(case_id, committed_events)
            self._write_derived_snapshot(case_id, committed_events, committed_record)
            return committed_record

    def _require_not_terminal(self, case_id: str, record: Optional[dict], target_stage: str) -> None:
        if record is not None and record["case_stage"] in TERMINAL_STAGES:
            raise envelope.InvalidTransitionError(
                f"case {case_id!r} is at terminal stage {record['case_stage']!r}; "
                f"{target_stage} can never be reached from a terminal stage"
            )

    # -- transitions -------------------------------------------------------
    def file_case(
        self,
        case_id: str,
        case_version: Any,
        claim: Optional[str],
        source_artifacts: Optional[Iterable[str]],
        requested_relief: Any = None,
        appeal_of: Optional[dict] = None,
    ) -> dict:
        case_id = envelope.validate_mission_id(case_id)

        if appeal_of is not None:
            referenced_case_id = appeal_of.get("case_id")
            referenced = self.get(referenced_case_id) if referenced_case_id else None
            if referenced is None:
                raise InvalidAppealReferenceError(
                    f"appeal_of names case_id {referenced_case_id!r}, which does not exist"
                )
            if referenced["case_stage"] not in TERMINAL_STAGES:
                raise InvalidAppealReferenceError(
                    f"case {referenced_case_id!r} is at {referenced['case_stage']!r}, not a terminal "
                    "stage; it cannot be appealed until it has been decided"
                )
            actual_hash = envelope._ledger_content_hash(self._read_ledger(referenced_case_id))
            if appeal_of.get("decision_content_hash") != actual_hash:
                raise InvalidAppealReferenceError(
                    f"appeal_of.decision_content_hash does not match the current ledger content "
                    f"hash of case {referenced_case_id!r}; an appeal must cite the exact decided "
                    "ledger state, not a stale or guessed one"
                )

        malformed_reason = None
        if source_artifacts is None or isinstance(source_artifacts, (str, bytes)):
            malformed_reason = "source_artifacts must be a non-string iterable of paths"
            source_artifacts = []
        else:
            source_artifacts = list(source_artifacts)

        if not claim or not str(claim).strip():
            malformed_reason = malformed_reason or "claim is missing or empty"

        if malformed_reason is None:
            missing = [a for a in source_artifacts if not Path(a).is_file()]
            if missing:
                malformed_reason = f"missing source artifact(s): {missing}"

        if malformed_reason is not None:
            return self.quarantine_case(
                case_id,
                case_version,
                reason=malformed_reason,
                raw_input={"claim": claim, "source_artifacts": source_artifacts},
            )

        content_hashes = {a: envelope.sha256_file(Path(a)) for a in source_artifacts}
        detail = {
            "case_version": case_version,
            "claim": claim,
            "source_artifacts": source_artifacts,
            "content_hashes": content_hashes,
            "requested_relief": requested_relief,
            "appeal_of": appeal_of,
        }
        key = envelope._event_key(case_id, "FILED", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "FILED",
            "event_key": key,
            "timestamp": envelope._now(),
            "detail": detail,
        }

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already and record is not None and record["case_stage"] is not None:
                raise CaseConflictError(
                    f"case_id {case_id!r} already has stage {record['case_stage']!r}; "
                    "cannot re-file as FILED with different content"
                )
            return event

        return self._commit(case_id, make_event)

    def quarantine_case(
        self, case_id: str, case_version: Any, reason: str, raw_input: Any = None
    ) -> dict:
        case_id = envelope.validate_mission_id(case_id)
        detail = {"case_version": case_version, "reason": reason, "raw_input": raw_input}
        key = envelope._event_key(case_id, "QUARANTINE", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "QUARANTINE",
            "event_key": key,
            "timestamp": envelope._now(),
            "detail": detail,
        }

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already:
                self._require_not_terminal(case_id, record, QUARANTINED)
            return event

        return self._commit(case_id, make_event)

    def rule_admissibility(self, case_id: str, evidence_sufficiency_checks: list) -> dict:
        case_id = envelope.validate_mission_id(case_id)
        detail = {"evidence_sufficiency_checks": evidence_sufficiency_checks}
        key = envelope._event_key(case_id, "ADMISSIBILITY_RULED", detail)
        resulting_stage = (
            ADMITTED
            if evidence_sufficiency_checks and all(bool(c.get("passed")) for c in evidence_sufficiency_checks)
            else INADMISSIBLE
        )
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "ADMISSIBILITY_RULED",
            "event_key": key,
            "timestamp": envelope._now(),
            "detail": detail,
            "resulting_stage": resulting_stage,
        }

        def make_event(record: Optional[dict], events: list) -> dict:
            already = any(e["event_key"] == key for e in events)
            if not already:
                if record is None:
                    raise envelope.InvalidTransitionError(f"no case found for case_id {case_id!r}")
                self._require_not_terminal(case_id, record, resulting_stage)
                if record["case_stage"] != FILED:
                    raise envelope.InvalidTransitionError(
                        f"case {case_id!r} is at {record['case_stage']!r}; an admissibility ruling "
                        f"requires {FILED}"
                    )
                if not evidence_sufficiency_checks:
                    raise envelope.AcceptanceEvidenceMissingError(
                        f"case {case_id!r} cannot receive an admissibility ruling without explicit "
                        "evidence_sufficiency_checks"
                    )
            return event

        return self._commit(case_id, make_event)

    def decide(
        self,
        case_id: str,
        ruling: str,
        decision_evidence: list,
        rationale: str,
        statement: str,
    ) -> dict:
        """Adjudicate an ADMITTED case. Requires a genuine, externally
        verified AuthorityVerifier result naming this exact case_id and
        an "adjudicate:<case_id>" scope -- fails closed with no verifier
        configured, an explicit rejection, a malformed result, the wrong
        scope, or a missing attestation. Once decided, the ruling is
        immutable: replaying the identical decision is a no-op; a
        *different* one for the same case raises AuthorityConflictError.
        """
        case_id = envelope.validate_mission_id(case_id)
        if ruling not in _RULINGS:
            raise ValueError(f"ruling must be one of {_RULINGS}, got {ruling!r}")

        if self.authority_verifier is None:
            raise envelope.AuthorityVerifierRequiredError(
                "EXTERNAL_AUTHORITY_VERIFIER_REQUIRED: no AuthorityVerifier is configured on this "
                "CourtStore; a case cannot be decided without one."
            )

        # Deliberately no unlocked pre-check of current stage here (unlike
        # an earlier draft of this method): the authoritative stage check
        # happens once, inside make_event below, against the record
        # reconstructed under this case's lock inside _commit -- so a
        # replay of an already-decided case is idempotent (short-circuited
        # by the existing-DECIDED-event check) rather than being rejected
        # by a stale read taken before the lock was even acquired.
        if not decision_evidence:
            raise envelope.AcceptanceEvidenceMissingError(
                f"case {case_id!r} cannot be decided without explicit decision_evidence"
            )

        required_scope = f"adjudicate:{case_id}"
        # NOTE: AuthorityVerificationRequest's `mission_id` field is filled
        # with this case's case_id -- the request/response contract is
        # generic (any subject_id + any scope), so it is reused verbatim
        # rather than defining a near-identical dataclass.
        request = envelope.AuthorityVerificationRequest(
            mission_id=case_id, requested_scope=required_scope, statement=statement
        )
        result = self.authority_verifier.verify(request)
        if result is None:
            raise envelope.AuthorityVerificationRejectedError(
                f"authority verification was rejected for case_id {case_id!r}"
            )
        _validate_verified_authority_for_case(result, case_id, required_scope)

        resulting_stage = APPROVED if ruling == APPROVED else REJECTED
        detail = {
            "ruling": ruling,
            "decision_evidence": decision_evidence,
            "rationale": rationale,
            "statement": statement,
            "principal_id": result.principal_id,
            "authority_scope": list(result.authority_scope),
            "verification_method": result.verification_method,
            "verified_at": result.verified_at,
            "attestation_reference": result.attestation_reference,
        }
        key = envelope._event_key(case_id, "DECIDED", detail)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "DECIDED",
            "event_key": key,
            "timestamp": envelope._now(),
            "detail": detail,
            "resulting_stage": resulting_stage,
        }

        def make_event(record: Optional[dict], events: list) -> dict:
            existing = next((e for e in events if e["transition"] == "DECIDED"), None)
            if existing is not None:
                if existing["event_key"] != key:
                    raise envelope.AuthorityConflictError(
                        f"case {case_id!r} already has a different recorded decision; a decision is "
                        "append-only and cannot be replaced (AUTHORITY_CONFLICT)"
                    )
                return event  # identical decision replayed: idempotent, handled by _commit
            if record is None:
                raise envelope.InvalidTransitionError(f"no case found for case_id {case_id!r}")
            self._require_not_terminal(case_id, record, resulting_stage)
            if record["case_stage"] != ADMITTED:
                raise envelope.InvalidTransitionError(
                    f"case {case_id!r} is at {record['case_stage']!r}; a decision requires {ADMITTED}"
                )
            return event

        return self._commit(case_id, make_event)
