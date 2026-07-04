#!/usr/bin/env python3
"""Capability Discovery: probes reachability of every registered capability.

Reachability is measured, not assumed. Each check type maps to a concrete
probe so the confidence score reflects what was actually observed on this
machine at this moment:
  command -> is the binary on PATH
  env     -> is the credential/env var present
  network -> can we open a TCP connection to the service
  self    -> the capability is this runtime itself (always reachable)
  manual  -> cannot be probed statically; operator must confirm (neutral 0.5)
"""
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "registry.json"
STATE_PATH = ROOT / "state.json"


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)["capabilities"]


def probe_one(check):
    check_type = check.get("type")
    if check_type == "command":
        found = shutil.which(check["value"]) is not None
        return (1.0 if found else 0.0), f"command '{check['value']}' {'found' if found else 'not found'} on PATH"
    if check_type == "env":
        present = bool(os.environ.get(check["value"]))
        return (1.0 if present else 0.0), f"env var '{check['value']}' {'set' if present else 'unset'}"
    if check_type == "network":
        host, _, port = check["value"].partition(":")
        try:
            socket.create_connection((host, int(port)), timeout=2).close()
            return 1.0, f"TCP connect to {check['value']} succeeded"
        except OSError as e:
            return 0.0, f"TCP connect to {check['value']} failed: {e}"
    if check_type == "self":
        return 1.0, "capability is the local runtime itself"
    if check_type == "manual":
        return 0.5, "static probe not possible; requires operator/runtime confirmation"
    return 0.0, f"unknown check type '{check_type}'"


def probe_all():
    results = {}
    for cap in load_registry():
        confidence, evidence = probe_one(cap["check"])
        results[cap["id"]] = {
            "reachability_confidence": confidence,
            "evidence": evidence,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    return results


def write_state(results):
    with open(STATE_PATH, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    state = probe_all()
    write_state(state)
    json.dump(state, sys.stdout, indent=2)
    print()
