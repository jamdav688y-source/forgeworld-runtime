"""Mission-and-Evidence Envelope substrate.

Bounded, file-backed lifecycle tracking for missions moving through
BRONZE_RECEIVED -> SILVER_STRUCTURED -> GOLD_VALIDATED, with REJECTED and
QUARANTINED as explicit failure / malformed-input destinations.

Every stage transition is an append-only ledger event. A mission's record
is a cached projection of its ledger, never an independent source of
truth -- reconstruct() rebuilds the same record purely by replaying the
ledger through the same projection function the live path uses
(_project_event), so history does not depend on the cache surviving.

Validation is not promotion: reaching GOLD_VALIDATED only means explicit
acceptance evidence was recorded. promotion_status only moves to PROMOTED
through record_promotion_authority(), a separate call that names a human
authority and is refused when the named actor looks machine-shaped.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

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

# Actor identifiers that must never be accepted as the human authority
# behind a promotion -- deliberately conservative: reject anything that
# names a model/agent/automation rather than a person.
_DISALLOWED_AUTHORITY_ACTORS = {
    "model", "agent", "ai", "runtime", "system", "automation",
    "automated", "self", "claude", "assistant", "bot", "forgeworld",
}

_STRUCTURED_METADATA_FIELDS = (
    "cognitive_roles_required",
    "capabilities_required",
    "context_budget",
    "privacy_tier",
    "authority_tier",
)


class EnvelopeError(Exception):
    """Base error for the mission-and-evidence envelope substrate."""


class MissionConflictError(EnvelopeError):
    """A mission_id already holds a different, non-replayed history."""


class InvalidTransitionError(EnvelopeError):
    """A transition was attempted from an incompatible lifecycle stage."""


class AcceptanceEvidenceMissingError(EnvelopeError):
    """GOLD_VALIDATED was attempted without explicit acceptance evidence."""


class SelfGrantedAuthorityError(EnvelopeError):
    """A promotion was attempted with a non-human authority actor."""


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


class EnvelopeStore:
    """File-backed store for mission-and-evidence envelopes.

    Each mission gets a cached snapshot at records/<mission_id>.json and an
    append-only event ledger at ledger/<mission_id>.jsonl.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.ledger_dir = self.root / "ledger"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)

    # -- storage helpers -----------------------------------------------
    def _record_path(self, mission_id: str) -> Path:
        return self.records_dir / f"{mission_id}.json"

    def _ledger_path(self, mission_id: str) -> Path:
        return self.ledger_dir / f"{mission_id}.jsonl"

    def _load(self, mission_id: str) -> Optional[dict]:
        path = self._record_path(mission_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def _save(self, record: dict) -> None:
        self._record_path(record["mission_id"]).write_text(
            json.dumps(record, indent=2, sort_keys=True)
        )

    def _read_ledger(self, mission_id: str) -> list:
        path = self._ledger_path(mission_id)
        if not path.exists():
            return []
        events = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def _append_ledger(self, mission_id: str, event: dict) -> None:
        with open(self._ledger_path(mission_id), "a") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    def get(self, mission_id: str) -> Optional[dict]:
        return self._load(mission_id)

    def reconstruct(self, mission_id: str) -> Optional[dict]:
        """Rebuild a mission's record purely by replaying its ledger,
        independent of the cached snapshot."""
        events = self._read_ledger(mission_id)
        if not events:
            return None
        record = _new_record(mission_id, mission_version=None)
        for event in events:
            record = _project_event(record, event)
        return record

    # -- shared commit path ----------------------------------------------
    def _commit(self, mission_id: str, record: Optional[dict], event: dict) -> dict:
        """Idempotently fold `event` onto `record` (creating one via
        _new_record if absent) and persist it, unless this exact event
        already is the last recorded one for this mission."""
        if record is not None and record["execution_events"]:
            if record["execution_events"][-1]["event_key"] == event["event_key"]:
                return record  # identical replay: no new event, no duplicate
        record = _project_event(record or _new_record(mission_id, None), event)
        self._append_ledger(mission_id, event)
        self._save(record)
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
        malformed_reason = None

        if source_artifacts is None or isinstance(source_artifacts, (str, bytes)):
            malformed_reason = "source_artifacts must be a non-string iterable of paths"
            source_artifacts = []
        else:
            source_artifacts = list(source_artifacts)
            if not source_artifacts:
                malformed_reason = "source_artifacts is empty"

        if not mission_id or not isinstance(mission_id, str):
            malformed_reason = malformed_reason or "mission_id is missing or not a string"
            mission_id = mission_id if isinstance(mission_id, str) and mission_id else f"UNKNOWN-{uuid.uuid4()}"

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

        record = self._load(mission_id)
        if record is not None and record["lifecycle_stage"] is not None:
            already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
            if not already:
                raise MissionConflictError(
                    f"mission_id {mission_id!r} already has stage {record['lifecycle_stage']!r}; "
                    "cannot re-receive as BRONZE with different content"
                )

        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "BRONZE_RECEIVED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }
        return self._commit(mission_id, record, event)

    def quarantine(
        self, mission_id: str, mission_version: Any, reason: str, raw_input: Any = None
    ) -> dict:
        detail = {"mission_version": mission_version, "reason": reason, "raw_input": raw_input}
        key = _event_key(mission_id, "QUARANTINE", detail)
        record = self._load(mission_id)
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "QUARANTINE",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }
        return self._commit(mission_id, record, event)

    def structure_silver(self, mission_id: str, structured_metadata: dict) -> dict:
        record = self._load(mission_id)
        if record is None:
            raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")

        detail = {"structured_metadata": structured_metadata}
        key = _event_key(mission_id, "SILVER_STRUCTURED", detail)
        already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
        if not already and record["lifecycle_stage"] != BRONZE_RECEIVED:
            raise InvalidTransitionError(
                f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                f"{SILVER_STRUCTURED} requires {BRONZE_RECEIVED}"
            )

        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "SILVER_STRUCTURED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }
        return self._commit(mission_id, record, event)

    def validate_gold(
        self, mission_id: str, acceptance_tests: list, evidence_artifacts: list
    ) -> dict:
        record = self._load(mission_id)
        if record is None:
            raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")

        detail = {"acceptance_tests": acceptance_tests, "evidence_artifacts": evidence_artifacts}
        key = _event_key(mission_id, "VALIDATE_GOLD", detail)
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

        resulting_stage = (
            GOLD_VALIDATED if all(bool(t.get("passed")) for t in acceptance_tests) else REJECTED
        )
        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "VALIDATE_GOLD",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
            "resulting_stage": resulting_stage,
        }
        return self._commit(mission_id, record, event)

    def reject(self, mission_id: str, reason: str) -> dict:
        record = self._load(mission_id)
        if record is None:
            raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")

        detail = {"reason": reason}
        key = _event_key(mission_id, "REJECTED", detail)
        already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
        if not already and record["lifecycle_stage"] not in (BRONZE_RECEIVED, SILVER_STRUCTURED):
            raise InvalidTransitionError(
                f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                f"{REJECTED} is only reachable from {BRONZE_RECEIVED} or {SILVER_STRUCTURED}"
            )

        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "REJECTED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }
        return self._commit(mission_id, record, event)

    def record_promotion_authority(
        self,
        mission_id: str,
        authorized_by: str,
        statement: str,
        authority_reference: Optional[str] = None,
    ) -> dict:
        if not authorized_by or authorized_by.strip().lower() in _DISALLOWED_AUTHORITY_ACTORS:
            raise SelfGrantedAuthorityError(
                f"authorized_by {authorized_by!r} is not an acceptable human authority identifier"
            )

        record = self._load(mission_id)
        if record is None:
            raise InvalidTransitionError(f"no envelope found for mission_id {mission_id!r}")

        detail = {
            "authorized_by": authorized_by,
            "statement": statement,
            "authority_reference": authority_reference,
        }
        key = _event_key(mission_id, "PROMOTION_AUTHORITY_RECORDED", detail)
        already = record["execution_events"] and record["execution_events"][-1]["event_key"] == key
        if not already and record["lifecycle_stage"] != GOLD_VALIDATED:
            raise InvalidTransitionError(
                f"mission {mission_id!r} is at {record['lifecycle_stage']!r}; "
                f"promotion requires {GOLD_VALIDATED}"
            )

        event = {
            "event_id": str(uuid.uuid4()),
            "transition": "PROMOTION_AUTHORITY_RECORDED",
            "event_key": key,
            "timestamp": _now(),
            "detail": detail,
        }
        return self._commit(mission_id, record, event)
