"""Append-only jsonl ledgers, matching the flat-file pattern used across the
rest of the repo (events/events.log, memory/memory.log) rather than
introducing a database this operator has no infrastructure for.

Concurrency: appends are serialized with an advisory OS file lock so two
processes (e.g. the webhook receiver and a concurrent CLI approval) writing
the same ledger at once cannot interleave partial writes into one corrupted
line. Reads are resilient to a corrupted line rather than failing the whole
ledger for every consumer -- a single bad line must not take down dedup
checks, consent lookups, or the approval queue for everyone else.
"""
import json
import sys
from pathlib import Path

try:
    import fcntl
    _HAVE_FLOCK = True
except ImportError:  # non-POSIX platform; append then falls back to unlocked writes
    _HAVE_FLOCK = False

MODULE_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = MODULE_ROOT / "ledgers"

CONVERSATION_LEDGER = LEDGER_DIR / "conversation_ledger.jsonl"
EXECUTION_LEDGER = LEDGER_DIR / "execution_ledger.jsonl"
CONSENT_LEDGER = LEDGER_DIR / "consent_ledger.jsonl"
OPPORTUNITY_LEDGER = LEDGER_DIR / "opportunity_ledger.jsonl"
SIGNAL_LEDGER = LEDGER_DIR / "signal_ledger.jsonl"


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(path, "a") as f:
        if _HAVE_FLOCK:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
        finally:
            if _HAVE_FLOCK:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_all(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    corrupt_path = path.with_suffix(path.suffix + ".corrupt")
    with open(path) as f:
        if _HAVE_FLOCK:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            lines = f.readlines()
        finally:
            if _HAVE_FLOCK:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Preserve the corrupted line for manual recovery instead of
            # silently discarding evidence; never let it crash every reader.
            print(f"WARNING: skipping corrupted ledger line in {path}", file=sys.stderr)
            try:
                with open(corrupt_path, "a") as cf:
                    cf.write(line + "\n")
            except OSError:
                pass
    return records


def find(path: Path, **filters) -> list:
    return [r for r in read_all(path) if all(r.get(k) == v for k, v in filters.items())]


def exists_by(path: Path, **filters) -> bool:
    return len(find(path, **filters)) > 0
