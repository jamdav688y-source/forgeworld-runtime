"""Append-only jsonl ledgers, matching the flat-file pattern used across the
rest of the repo (events/events.log, memory/memory.log) rather than
introducing a database this operator has no infrastructure for.
"""
import json
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = MODULE_ROOT / "ledgers"

CONVERSATION_LEDGER = LEDGER_DIR / "conversation_ledger.jsonl"
EXECUTION_LEDGER = LEDGER_DIR / "execution_ledger.jsonl"
CONSENT_LEDGER = LEDGER_DIR / "consent_ledger.jsonl"
OPPORTUNITY_LEDGER = LEDGER_DIR / "opportunity_ledger.jsonl"
SIGNAL_LEDGER = LEDGER_DIR / "signal_ledger.jsonl"


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def read_all(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def find(path: Path, **filters) -> list:
    return [r for r in read_all(path) if all(r.get(k) == v for k, v in filters.items())]


def exists_by(path: Path, **filters) -> bool:
    return len(find(path, **filters)) > 0
