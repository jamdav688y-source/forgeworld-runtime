"""FW-CXP-R1-IMPLEMENTATION-001: the local Cognitive Exchange -- accepts
CXP v1 events, persists them, and delivers each accepted record to a set of
independent consumers exactly once per (consumer, record).

PROCESSING CONTRACT
  ingest(raw_event) ->
    1. parse_event()       structural validation; any failure -> REJECTED,
                           nothing written.
    2. under the store lock:
         record erased                     -> REJECTED (RECORD_ERASED), even
                                              for an exact replay
         occurrence already recorded       -> DUPLICATE_OCCURRENCE (exact replay)
         record already accepted           -> DUPLICATE_RECORD (new sighting of
                                              known content+lineage; the new
                                              occurrence is recorded)
         otherwise resolve_lineage(), then -> ACCEPTED (record + occurrence
                                              committed in one atomic write)
         a CONTRADICTION over a claim set that already has a live
         contradiction                     -> REJECTED (DUPLICATE_CONTRADICTION)
         a COMMERCIAL_SIGNAL the engagement's current state does not
         allow (cognition.commerce)        -> REJECTED (TRANSITION_REFUSED)
    3. dispatch: every registered consumer that has no CONSUMED result for
       this record_id is called; consumers that already consumed it are not
       (idempotency is keyed on record_id, never on occurrence_id). A
       consumer that raises, or returns invalid output, gets a FAILED entry
       and is retried on the next delivery of the same record; it never
       affects any other consumer.

  Consumers are independent: each gets the same immutable CognitiveRecord
  (payload() hands each caller a fresh copy), never sees another consumer's
  output, and is isolated from other consumers' exceptions. Consumers run
  outside the store lock; under concurrent delivery a consumer may be
  invoked more than once for one record, but only the first CONSUMED result
  is ever recorded (at-least-once invocation, exactly-once recorded result).

PERSISTENCE (one store directory)
  exchange.jsonl    append-only ledger of payload-free metadata: RECORD,
                    OCCURRENCE, CONSUMER_RESULT, TOMBSTONE entries. Written
                    with evidence_envelope's lock + atomic-replace discipline
                    (reused, not refactored -- the known whole-file-rewrite
                    cost is accepted for R1). Contains no wall-clock time, so
                    the same events in the same order produce a
                    byte-identical ledger.
  payloads/<record_id>.json   erasable record payloads.
  outputs/<result_id>.json    erasable consumer outputs (they may be derived
                              from payload content, so they are erased with it).
  erase(record_id) deletes the record's payload and every consumer output
  for it, and appends a TOMBSTONE. The ledger still holds content_id,
  source locators and output digests: a hash of low-entropy content is NOT
  automatically privacy-safe, which is why R1 refuses to persist PERSONAL
  or RESTRICTED records at all (PRIVACY_PERSISTENCE_UNSUPPORTED).

AUTHORITY: this module issues no grants, touches no pairing/peer/grant
store, imports nothing from fabric/ or substrate/, and every receipt
answers grants_execution_authority -> False.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evidence_envelope import envelope  # noqa: E402
from cognition import cxp  # noqa: E402

ACCEPTED = "ACCEPTED"
DUPLICATE_RECORD = "DUPLICATE_RECORD"
DUPLICATE_OCCURRENCE = "DUPLICATE_OCCURRENCE"
REJECTED = "REJECTED"

CONSUMED = "CONSUMED"
FAILED = "FAILED"
ALREADY_CONSUMED = "ALREADY_CONSUMED"  # receipt-only; never written to the ledger

_ENTRY_RECORD = "RECORD"
_ENTRY_OCCURRENCE = "OCCURRENCE"
_ENTRY_CONSUMER_RESULT = "CONSUMER_RESULT"
_ENTRY_TOMBSTONE = "TOMBSTONE"
_ENTRY_TYPES = (_ENTRY_RECORD, _ENTRY_OCCURRENCE, _ENTRY_CONSUMER_RESULT, _ENTRY_TOMBSTONE)

_PERSISTABLE_PRIVACY = (cxp.PRIV_PUBLIC, cxp.PRIV_INTERNAL)


class Consumer(Protocol):
    """An independent processor of accepted records. consume() must return
    a JSON-canonicalizable dict free of authority-shaped keys; anything
    else is recorded as FAILED. It must not rely on any other consumer."""

    consumer_id: str

    def consume(self, record: cxp.CognitiveRecord) -> dict: ...


@dataclass(frozen=True)
class ConsumerResult:
    consumer_id: str
    record_id: str
    status: str
    result_id: Optional[str] = None
    error_type: Optional[str] = None


@dataclass(frozen=True)
class IngestReceipt:
    status: str
    record_id: Optional[str] = None
    occurrence_id: Optional[str] = None
    error_code: Optional[str] = None
    detail: Optional[str] = None
    consumer_results: tuple = ()

    @property
    def grants_execution_authority(self) -> bool:
        return False


class _State:
    def __init__(self):
        self.records = {}      # record_id -> stored metadata
        self.occurrences = set()
        self.consumed = {}     # (consumer_id, record_id) -> result_id
        self.erased = set()

    def lookup(self, record_id: str) -> Optional[dict]:
        meta = self.records.get(record_id)
        if meta is None:
            return None
        return {**meta, "erased": record_id in self.erased}


class CognitiveExchange:
    def __init__(self, root: Path, consumers=(), lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self.root / "exchange.jsonl"
        self._lock_path = self.root / "exchange.lock"
        self._payload_dir = self.root / "payloads"
        self._output_dir = self.root / "outputs"
        self._lock_timeout = lock_timeout_seconds
        seen = set()
        for consumer in consumers:
            consumer_id = cxp._validate_identifier(getattr(consumer, "consumer_id", None), "consumer_id")
            if consumer_id in seen:
                raise ValueError(f"duplicate consumer_id {consumer_id!r}")
            seen.add(consumer_id)
        self.consumers = tuple(consumers)

    # -- ledger ---------------------------------------------------------------

    def _lock(self):
        return envelope._FileLock(self._lock_path, timeout_seconds=self._lock_timeout)

    def _read_entries(self) -> list:
        if not self._ledger_path.exists():
            return []
        entries = []
        with open(self._ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(f"{self._ledger_path} line {line_number} is not newline-terminated")
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    raise envelope.LedgerIntegrityError(f"{self._ledger_path} line {line_number} is not JSON") from None
                if not isinstance(entry, dict) or entry.get("entry") not in _ENTRY_TYPES:
                    raise envelope.LedgerIntegrityError(f"{self._ledger_path} line {line_number} has no known entry type")
                entries.append(entry)
        return entries

    def _load(self) -> _State:
        state = _State()
        for entry in self._read_entries():
            kind = entry["entry"]
            if kind == _ENTRY_RECORD:
                meta = entry["metadata"]
                identity = {k: meta[k] for k in (
                    "schema_version", "content_id", "evidence", "verification", "provenance", "privacy",
                    "sources", "derived_from", "verification_ref", "consent_ref")}
                if cxp.digest_id("record", identity) != meta["record_id"]:
                    raise envelope.LedgerIntegrityError(f"record {meta['record_id']} does not match its identity fields")
                state.records[meta["record_id"]] = meta
            elif kind == _ENTRY_OCCURRENCE:
                state.occurrences.add(entry["occurrence_id"])
            elif kind == _ENTRY_CONSUMER_RESULT:
                if entry["status"] == CONSUMED:
                    state.consumed.setdefault((entry["consumer_id"], entry["record_id"]), entry["result_id"])
            elif kind == _ENTRY_TOMBSTONE:
                state.erased.add(entry["record_id"])
        return state

    def _append(self, new_entries: list) -> None:
        entries = self._read_entries()
        envelope._atomic_write_bytes(self._ledger_path, envelope._serialize_ledger(entries + new_entries))

    # -- ingest ---------------------------------------------------------------

    def ingest(self, raw_event) -> IngestReceipt:
        try:
            record, occurrence = cxp.parse_event(raw_event)
            if record.privacy not in _PERSISTABLE_PRIVACY:
                raise cxp.CXPError(cxp.E_PRIVACY_PERSISTENCE_UNSUPPORTED,
                                   f"R1 persists only {_PERSISTABLE_PRIVACY} records")
        except cxp.CXPError as exc:
            return IngestReceipt(status=REJECTED, error_code=exc.code, detail=exc.detail)

        with self._lock():
            state = self._load()
            if record.record_id in state.erased:
                return IngestReceipt(status=REJECTED, record_id=record.record_id, error_code=cxp.E_ERASED,
                                     detail="record has been erased and will not be re-accepted")
            elif occurrence.occurrence_id in state.occurrences:
                status = DUPLICATE_OCCURRENCE
            elif record.record_id in state.records:
                self._append([{"entry": _ENTRY_OCCURRENCE, **occurrence.to_dict()}])
                status = DUPLICATE_RECORD
            else:
                try:
                    root_sources = cxp.resolve_lineage(record, state.lookup)
                    if record.kind == cxp.KIND_CONTRADICTION:
                        self._refuse_duplicate_contradiction(record, state)
                    elif record.kind == cxp.KIND_COMMERCIAL_SIGNAL:
                        from cognition import commerce  # deferred: commerce reads exchange state, never imports it
                        commerce.check_transition(
                            commerce.commerce_metadata(record.payload()),
                            {rid: m["commerce"] for rid, m in state.records.items() if "commerce" in m},
                            state.erased)
                    elif record.kind == cxp.KIND_PRODUCTION_PACKAGE:
                        from cognition import production
                        production.check_transition(record.payload(), state.lookup,
                                                    {rid: state.lookup(rid) for rid in state.records})
                    elif record.kind == cxp.KIND_PACKAGE_REVIEW:
                        from cognition import package_revision
                        package_revision.check_review_transition(record.payload(), state.lookup)
                    elif record.kind == cxp.KIND_PRODUCTION_HANDOFF:
                        from cognition import handoff
                        handoff.check_transition(record.payload(), state.lookup,
                                                 {rid: state.lookup(rid) for rid in state.records})
                    elif record.kind in (cxp.KIND_DELIVERY_PACKAGE, cxp.KIND_DELIVERY_EVENT):
                        from cognition import delivery
                        check = (delivery.check_package_transition if record.kind == cxp.KIND_DELIVERY_PACKAGE
                                 else delivery.check_event_transition)
                        check(record.payload(), state.lookup, {rid: state.lookup(rid) for rid in state.records})
                    elif record.kind == cxp.KIND_OUTCOME_SPEC:
                        from cognition import destination
                        destination.check_spec_transition(record.payload(), state.lookup)
                    elif record.kind in (cxp.KIND_EPISODE_CANDIDATE, cxp.KIND_EPISODE_REVIEW):
                        from cognition import episode
                        episode.check_transition(record.kind, record.payload(),
                                                 {rid: state.lookup(rid) for rid in state.records}, state.lookup)
                except cxp.CXPError as exc:
                    return IngestReceipt(status=REJECTED, record_id=record.record_id, error_code=exc.code,
                                         detail=exc.detail)
                self._commit_new_record(record, occurrence, root_sources)
                status = ACCEPTED

        results = tuple(self._deliver(consumer, record) for consumer in self.consumers)
        return IngestReceipt(status=status, record_id=record.record_id, occurrence_id=occurrence.occurrence_id,
                             consumer_results=results)

    @staticmethod
    def _refuse_duplicate_contradiction(record: cxp.CognitiveRecord, state: _State) -> None:
        """One live contradiction per claim set: re-asserting a known
        disagreement in new words must not make it look more established."""
        for record_id, meta in sorted(state.records.items()):
            if (meta.get("contradiction_claims") == list(record.derived_from)
                    and record_id not in state.erased):
                raise cxp.CXPError(cxp.E_DUPLICATE_CONTRADICTION,
                                   f"claim set already recorded as contradiction {record_id}")

    def _commit_new_record(self, record: cxp.CognitiveRecord, occurrence: cxp.Occurrence, root_sources: tuple) -> None:
        meta = {**record.metadata(), "root_sources": list(root_sources)}
        if record.kind == cxp.KIND_VERIFICATION_RESULT:
            payload = record.payload()
            meta["verification_target"] = payload["target_content_id"]
            meta["verification_outcome"] = payload["outcome"]
            meta["verification_method"] = payload["method"]
        elif record.kind == cxp.KIND_CONTRADICTION:
            meta["contradiction_claims"] = list(record.derived_from)
        elif record.kind == cxp.KIND_LENS_OUTPUT:
            payload = record.payload()
            meta["lens_id"] = payload["lens_id"]
            meta["lens_version"] = payload["lens_version"]
            meta["lens_positions"] = payload["positions"]
        elif record.kind == cxp.KIND_COMMERCIAL_SIGNAL:
            from cognition import commerce
            meta["commerce"] = commerce.commerce_metadata(record.payload())
        elif record.kind == cxp.KIND_AUDIENCE_QUESTION:
            from cognition import audience
            meta["audience"] = audience.audience_metadata(record.payload())
        elif record.kind == cxp.KIND_EPISODE_CANDIDATE:
            from cognition import episode
            meta["episode"] = episode.candidate_metadata(record.payload())
        elif record.kind == cxp.KIND_EPISODE_REVIEW:
            from cognition import episode
            meta["episode_review"] = episode.review_metadata(record.payload())
        elif record.kind == cxp.KIND_PRODUCTION_PACKAGE:
            payload = record.payload()
            meta["production_package"] = {k: payload[k] for k in ("package_id", "candidate_id", "review_id", "cycle_id",
                                                                  "package_revision", "predecessor_record_id", "editor")}
        elif record.kind == cxp.KIND_PACKAGE_REVIEW:
            payload = record.payload()
            meta["package_review"] = {k: payload[k] for k in ("package_record_id", "package_id", "decision", "reviewer")}
        elif record.kind == cxp.KIND_PRODUCTION_HANDOFF:
            payload = record.payload()
            meta["production_handoff"] = {k: payload[k] for k in ("handoff_id", "package_record_id", "package_id",
                                                                  "package_review_id", "signer")}
        elif record.kind == cxp.KIND_DELIVERY_PACKAGE:
            from cognition import delivery
            meta["delivery_package"] = delivery.package_metadata(record.payload())
        elif record.kind == cxp.KIND_DELIVERY_EVENT:
            from cognition import delivery
            meta["delivery_event"] = delivery.event_metadata(record.payload())
        elif record.kind == cxp.KIND_OUTCOME_SPEC:
            from cognition import destination
            meta["outcome_spec"] = destination.spec_metadata(record.payload())
        self._payload_dir.mkdir(parents=True, exist_ok=True)
        payload_path = self._payload_dir / f"{record.record_id}.json"
        envelope._atomic_write_bytes(payload_path, record.payload_json.encode("utf-8"))
        try:
            self._append([{"entry": _ENTRY_RECORD, "record_id": record.record_id, "metadata": meta},
                          {"entry": _ENTRY_OCCURRENCE, **occurrence.to_dict()}])
        except BaseException:
            payload_path.unlink(missing_ok=True)  # never leave an uncommitted payload behind
            raise

    # -- dispatch -------------------------------------------------------------

    def _deliver(self, consumer, record: cxp.CognitiveRecord) -> ConsumerResult:
        key = (consumer.consumer_id, record.record_id)
        consumed = self._load().consumed
        if key in consumed:
            return ConsumerResult(consumer.consumer_id, record.record_id, ALREADY_CONSUMED, result_id=consumed[key])
        output_json, error_type = None, None
        try:
            output = consumer.consume(record)
            if not isinstance(output, dict):
                raise cxp.CXPError(cxp.E_MALFORMED, "consumer output must be an object")
            cxp.check_no_authority_fields(output, "consumer output")
            output_json = cxp.canonical_bytes(output).decode("utf-8")
        except cxp.CXPError as exc:
            error_type = f"CXPError:{exc.code}"
        except Exception as exc:  # noqa: BLE001 -- one consumer's failure must never reach another
            error_type = type(exc).__name__

        with self._lock():
            state = self._load()
            if key in state.consumed:
                return ConsumerResult(consumer.consumer_id, record.record_id, ALREADY_CONSUMED,
                                      result_id=state.consumed[key])
            if record.record_id in state.erased:
                return ConsumerResult(consumer.consumer_id, record.record_id, FAILED, error_type=cxp.E_ERASED)
            if error_type is not None:
                self._append([{"entry": _ENTRY_CONSUMER_RESULT, "consumer_id": consumer.consumer_id,
                               "record_id": record.record_id, "status": FAILED, "result_id": None,
                               "output_sha256": None, "error_type": error_type}])
                return ConsumerResult(consumer.consumer_id, record.record_id, FAILED, error_type=error_type)
            result_id = cxp.digest_id("result", {"consumer_id": consumer.consumer_id, "record_id": record.record_id,
                                                 "output": json.loads(output_json)})
            self._output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self._output_dir / f"{result_id}.json"
            envelope._atomic_write_bytes(output_path, output_json.encode("utf-8"))
            try:
                self._append([{"entry": _ENTRY_CONSUMER_RESULT, "consumer_id": consumer.consumer_id,
                               "record_id": record.record_id, "status": CONSUMED, "result_id": result_id,
                               "output_sha256": hashlib.sha256(output_json.encode("utf-8")).hexdigest(),
                               "error_type": None}])
            except BaseException:
                output_path.unlink(missing_ok=True)
                raise
            return ConsumerResult(consumer.consumer_id, record.record_id, CONSUMED, result_id=result_id)

    # -- reads ----------------------------------------------------------------

    def record_metadata(self, record_id: str) -> Optional[dict]:
        return self._load().lookup(record_id)

    def all_record_metadata(self) -> tuple:
        """Every accepted record's payload-free metadata (erased ones flagged),
        sorted by record_id."""
        state = self._load()
        return tuple(state.lookup(record_id) for record_id in sorted(state.records))

    def get_record(self, record_id: str) -> Optional[cxp.CognitiveRecord]:
        """The full record, or None if unknown or erased. Fails closed if the
        stored payload no longer matches the record's content_id."""
        meta = self.record_metadata(record_id)
        if meta is None or meta["erased"]:
            return None
        payload_json = (self._payload_dir / f"{record_id}.json").read_text(encoding="utf-8")
        content_id = cxp.digest_id("content", {"kind": meta["kind"], "representation": meta["representation"],
                                               "payload": json.loads(payload_json)})
        if content_id != meta["content_id"]:
            raise envelope.LedgerIntegrityError(f"payload for {record_id} does not match its content_id")
        return cxp.CognitiveRecord(
            schema_version=meta["schema_version"], kind=meta["kind"], representation=meta["representation"],
            evidence=meta["evidence"], verification=meta["verification"], provenance=meta["provenance"],
            privacy=meta["privacy"], payload_json=payload_json,
            sources=tuple(cxp.SourceRef(**s) for s in meta["sources"]), derived_from=tuple(meta["derived_from"]),
            verification_ref=meta["verification_ref"], consent_ref=meta["consent_ref"],
            content_id=meta["content_id"], record_id=record_id,
        )

    def consumer_output(self, consumer_id: str, record_id: str) -> Optional[dict]:
        state = self._load()
        result_id = state.consumed.get((consumer_id, record_id))
        if result_id is None or record_id in state.erased:
            return None
        return json.loads((self._output_dir / f"{result_id}.json").read_text(encoding="utf-8"))

    def ledger_entries(self) -> tuple:
        return tuple(self._read_entries())

    def state_digest(self) -> str:
        """Deterministic fingerprint of what this exchange has accepted and
        processed -- identical for identical event sequences."""
        state = self._load()
        summary = {
            "records": sorted(state.records), "occurrences": sorted(state.occurrences),
            "consumed": sorted([c, r, res] for (c, r), res in state.consumed.items()),
            "erased": sorted(state.erased),
        }
        return hashlib.sha256(cxp.canonical_bytes(summary)).hexdigest()

    # -- erasure --------------------------------------------------------------

    def erase(self, record_id: str, reason: str) -> None:
        """Delete erasable content (payload and consumer outputs) and append a
        TOMBSTONE. Payload-free lineage metadata stays so descendants remain
        auditable; new derivations from an erased record are refused."""
        reason = cxp._validate_identifier(reason, "erasure reason")
        with self._lock():
            state = self._load()
            if record_id not in state.records:
                raise KeyError(record_id)
            if record_id in state.erased:
                return
            self._append([{"entry": _ENTRY_TOMBSTONE, "record_id": record_id, "reason": reason}])
            (self._payload_dir / f"{record_id}.json").unlink(missing_ok=True)
            for (_, rid), result_id in state.consumed.items():
                if rid == record_id:
                    (self._output_dir / f"{result_id}.json").unlink(missing_ok=True)
