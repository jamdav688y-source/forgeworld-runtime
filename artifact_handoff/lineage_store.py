"""Durable artifact lineage: a second, smaller ledger built directly on
evidence_envelope.py's already-tested atomic-write/file-lock primitives,
the same way trajectory.py already extends envelope.py without touching
EnvelopeStore's BRONZE/SILVER/GOLD mission-lifecycle machinery.

MISSION: FW-DURABLE-ARTIFACT-LINEAGE-001 (FW-PERMANENT-OFFLINE-SUBSTRATE-001,
Microphase 01).

WHAT THIS IS: append-only, durable storage for interface.Manifest.to_dict()
records, keyed by artifact_id, so an artifact's identity, digest, origin,
parentage, descendants, classification, safety disposition, routing
decision, and capability selection all survive process termination.

WHAT THIS IS NOT: this module never imports evidence_envelope.EnvelopeStore
and never touches mission promotion/evidence machinery. Storing a
Manifest here is I/O only -- it does not create evidence, does not confer
authority, and does not change any of the Manifest's own fixed invariant
properties (trust_status/execution_status/validation_status/
evidence_status/authority_status/promotion_status stay exactly what
interface.py already set; this module reads and writes them verbatim,
never interprets or upgrades them).

DURABILITY: mirrors trajectory.TrajectoryStore exactly -- a single JSONL
ledger, one per-store cross-process lock (envelope._FileLock), one atomic
whole-file replace per write (envelope._atomic_write_bytes /
_serialize_ledger). A corrupted ledger fails closed with
envelope.LedgerIntegrityError rather than silently skipping or
"recovering" a bad line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from evidence_envelope import envelope  # noqa: E402 -- _FileLock / _atomic_write_bytes / _serialize_ledger / LedgerIntegrityError / validate_mission_id only


class LineageStoreError(envelope.EnvelopeError):
    """Base error for this module."""


class LineageConflictError(LineageStoreError):
    """An artifact_id already holds a different, non-identical record.

    Lineage records are append-only, mirroring trajectory.py's run_id
    contract: an identical re-record of the same artifact_id is an
    idempotent no-op; a different one for the same artifact_id is
    refused outright, never silently overwritten.
    """


class LineageStore:
    """Append-only ledger of artifact manifests, one JSONL file per store
    root. Reuses envelope.py's durability primitives directly -- this is
    not a third durability implementation, it is the same discipline
    applied to a different, smaller record shape (an artifact manifest,
    not a BRONZE/SILVER/GOLD mission or a trajectory run)."""

    def __init__(self, root: Path, lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "artifact_lineage.jsonl"
        self.lock_path = self.root / "artifact_lineage.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    def _read_all(self) -> list:
        if not self.ledger_path.exists():
            return []
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(
                        f"artifact lineage ledger {self.ledger_path} line {line_number} is not "
                        "newline-terminated (truncated or partially written)"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    raise envelope.LedgerIntegrityError(
                        f"artifact lineage ledger {self.ledger_path} line {line_number} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(record, dict) or "artifact_id" not in record:
                    raise envelope.LedgerIntegrityError(
                        f"artifact lineage ledger {self.ledger_path} line {line_number} is missing "
                        "required field 'artifact_id'"
                    )
                records.append(record)
        return records

    def record(self, manifest_dict: dict) -> dict:
        """Append `manifest_dict` (as produced by interface.Manifest.to_dict())
        durably and atomically, under this store's cross-process lock.
        Identical re-recording of the same artifact_id is an idempotent
        no-op; recording different content under an already-used
        artifact_id raises LineageConflictError -- artifact_id identity
        is append-only, never silently overwritten."""
        artifact_id = manifest_dict.get("artifact_id")
        envelope.validate_mission_id(artifact_id)

        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all()
            existing = next((r for r in records if r["artifact_id"] == artifact_id), None)
            if existing is not None:
                if existing == manifest_dict:
                    return existing
                raise LineageConflictError(
                    f"artifact_id {artifact_id!r} already recorded with different content"
                )
            envelope._atomic_write_bytes(
                self.ledger_path, envelope._serialize_ledger(records + [manifest_dict])
            )
            return manifest_dict

    def get(self, artifact_id: str) -> Optional[dict]:
        artifact_id = envelope.validate_mission_id(artifact_id)
        return next((r for r in self._read_all() if r["artifact_id"] == artifact_id), None)

    def list_all(self) -> list:
        return self._read_all()

    def children_of(self, artifact_id: str) -> list:
        artifact_id = envelope.validate_mission_id(artifact_id)
        return [r for r in self._read_all() if r.get("parent_artifact_id") == artifact_id]

    def reconstruct_lineage(self, artifact_id: str) -> Optional[dict]:
        """Return {"artifact": <dict>, "ancestor_ids": [...], "descendants":
        [<dict>, ...]} for `artifact_id`, or None if it is not in the
        store. Ancestors come straight from the artifact's own stored
        provenance_lineage (already computed once, at handoff time);
        descendants are found by walking child_artifact_ids/
        parent_artifact_id recursively over the live ledger, so this
        reflects whatever is actually persisted, not just what one
        manifest claims about itself."""
        records = self._read_all()
        by_id = {r["artifact_id"]: r for r in records}
        artifact = by_id.get(artifact_id)
        if artifact is None:
            return None

        descendants = []
        frontier = list(artifact.get("child_artifact_ids", []))
        seen = set()
        while frontier:
            child_id = frontier.pop()
            if child_id in seen:
                continue
            seen.add(child_id)
            child = by_id.get(child_id)
            if child is None:
                continue
            descendants.append(child)
            frontier.extend(child.get("child_artifact_ids", []))

        return {
            "artifact": artifact,
            "ancestor_ids": list(artifact.get("provenance_lineage", [])),
            "descendants": descendants,
        }
