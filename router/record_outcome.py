#!/usr/bin/env python3
"""Record a validated execution outcome as evidence for future routing.

The router only learns from validated execution records (Continuity Law /
Adaptive Learning: "Learn only from validated execution records"). This
script is the single write path into capabilities/history.jsonl -- nothing
else should append to that file by hand.
"""
import argparse
import json
import time
from pathlib import Path

HISTORY_PATH = Path(__file__).resolve().parent.parent / "capabilities" / "history.jsonl"


def record(capability_id, mission_class, success_score, notes=""):
    entry = {
        "capability_id": capability_id,
        "mission_class": mission_class,
        "success_score": max(0.0, min(1.0, success_score)),
        "notes": notes,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def main():
    parser = argparse.ArgumentParser(description="Record a validated execution outcome.")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--mission-class", required=True, help="Use the same value as the routing decision's mission_class field.")
    parser.add_argument("--success-score", type=float, required=True, help="0.0 (failed) to 1.0 (fully succeeded).")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    entry = record(args.capability_id, args.mission_class, args.success_score, args.notes)
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
