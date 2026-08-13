"""Evidence records and evidence-state derivation.

Execution success is not evidence strength, and evidence strength is not
promotion. This module owns the first half of that sentence; promotion.py
owns the second.

Vocabulary (UNKNOWN, OBSERVED, SUPPORTED, VALIDATED, INSTITUTIONALIZED) is
adopted from the staged-strength language already present in
governance/EVOLUTION_DIRECTIVE_v1.txt and the EVENT -> EVIDENCE -> MEMORY
-> REPUTATION chain in governance/CONSTITUTION_v3.txt, not invented fresh.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from governance.types import EvidenceState, SCHEMA_VERSION

GOVERNANCE_DIR = Path(__file__).resolve().parent
DEFAULT_EVIDENCE_PATH = GOVERNANCE_DIR / "evidence_log.jsonl"


@dataclass
class EvidenceRecord:
    evidence_id: str
    subject: str
    state: EvidenceState
    observation: str
    source: str
    recorded_at: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append(record: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def record_evidence(
    subject: str,
    observation: str,
    source: str,
    state: EvidenceState = EvidenceState.OBSERVED,
    path: Optional[Path] = None,
) -> EvidenceRecord:
    """Record a single, attributable observation. Low-level primitive --
    prefer observe()/validate()/institutionalize() below for the common
    cases, since they enforce the staged-escalation rules.
    """
    path = path or DEFAULT_EVIDENCE_PATH
    record = EvidenceRecord(
        evidence_id=f"EVID-{uuid.uuid4().hex[:12]}",
        subject=subject,
        state=state,
        observation=observation,
        source=source,
        recorded_at=_now(),
    )
    _append(record.to_dict(), path)
    return record


def observe(subject: str, observation: str, source: str, path: Optional[Path] = None) -> EvidenceRecord:
    """A single, unreinforced observation. State: OBSERVED."""
    return record_evidence(subject, observation, source, EvidenceState.OBSERVED, path)


def validate(
    subject: str,
    observation: str,
    validated_by: str,
    verification_method: str,
    path: Optional[Path] = None,
) -> EvidenceRecord:
    """Record an explicit, independent verification (e.g. re-running the
    adversarial suite against a corrected server, not just trusting the
    first success report). State: VALIDATED.
    """
    full_observation = f"{observation} (verification_method={verification_method})"
    return record_evidence(subject, full_observation, validated_by, EvidenceState.VALIDATED, path)


def institutionalize(
    subject: str,
    observation: str,
    decision_ref: str,
    path: Optional[Path] = None,
) -> EvidenceRecord:
    """Record that a validated fact has been incorporated into durable
    governance state (e.g. a promotion actually granted, a tag actually
    frozen as baseline). State: INSTITUTIONALIZED. `decision_ref` should
    point at the authorizing record (an approval_id, a promotion_id, ...).
    """
    full_observation = f"{observation} (decision_ref={decision_ref})"
    return record_evidence(subject, full_observation, "governance", EvidenceState.INSTITUTIONALIZED, path)


def _read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def evidence_for(subject: str, path: Optional[Path] = None) -> list[EvidenceRecord]:
    path = path or DEFAULT_EVIDENCE_PATH
    out = []
    for r in _read_all(path):
        if r["subject"] == subject:
            r = dict(r)
            r["state"] = EvidenceState(r["state"])
            out.append(EvidenceRecord(**r))
    return out


def current_evidence_state(subject: str, path: Optional[Path] = None) -> EvidenceState:
    """Derive the current evidence strength for `subject`.

    Precedence:
      - any INSTITUTIONALIZED record -> INSTITUTIONALIZED
      - any VALIDATED record         -> VALIDATED
      - any SUPPORTED record, OR >=2 OBSERVED records from distinct
        sources (independent corroboration, matching
        EVOLUTION_DIRECTIVE_v1.txt: "No memory becomes reputation until
        multiple observations reinforce it") -> SUPPORTED
      - >=1 OBSERVED record          -> OBSERVED
      - nothing recorded             -> UNKNOWN
    """
    records = evidence_for(subject, path)
    if not records:
        return EvidenceState.UNKNOWN
    if any(r.state == EvidenceState.INSTITUTIONALIZED for r in records):
        return EvidenceState.INSTITUTIONALIZED
    if any(r.state == EvidenceState.VALIDATED for r in records):
        return EvidenceState.VALIDATED
    observed_sources = {r.source for r in records if r.state == EvidenceState.OBSERVED}
    if any(r.state == EvidenceState.SUPPORTED for r in records) or len(observed_sources) >= 2:
        return EvidenceState.SUPPORTED
    if any(r.state == EvidenceState.OBSERVED for r in records):
        return EvidenceState.OBSERVED
    return EvidenceState.UNKNOWN
