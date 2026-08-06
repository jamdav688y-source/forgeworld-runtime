#!/usr/bin/env python3
"""Capability Discovery: probes reachability of every registered capability.

Reachability is measured, not assumed. Each check type maps to a concrete
probe so the confidence score reflects what was actually observed on this
machine at this moment:
  command   -> is the binary on PATH
  env       -> is the credential/env var present
  network   -> can we open a TCP connection to the service
  self      -> the capability is this runtime itself (always reachable)
  manual    -> cannot be probed statically; operator must confirm (neutral 0.5)
  platform  -> does platform.system() match the required OS (deterministic,
               e.g. Windows-only capabilities correctly read UNAVAILABLE
               when this process is running on Linux)
  connector -> is this id present in a live connector-status list. That
               list can only come from the calling agent (a plain Python
               process here has no way to query a host's connector
               session) -- pass it via probe_all(live_connectors=[...]).
               Without one, this resolves to the neutral 'unconfirmed'
               reading, same as 'manual', rather than guessing.
  termux    -> are we actually running inside Termux right now. Checked
               via TERMUX_VERSION / PREFIX env vars (the standard Termux
               markers), NOT platform.system() -- Termux's Python reports
               platform.system() == 'Linux', same as any other Linux
               process, so a plain platform check can never distinguish
               "real Android/Termux" from "a Linux container" and would
               silently misclassify both directions. This deterministically
               reads UNAVAILABLE outside Termux (e.g. in this cloud
               container) rather than guessing.
"""
import json
import os
import platform
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
    if check_type == "platform":
        actual = platform.system()
        matched = actual == check["value"]
        return (1.0 if matched else 0.0), f"platform.system()='{actual}', required '{check['value']}'"
    if check_type == "connector":
        return 0.0, f"connector '{check['value']}' unconfirmed: no live connector list supplied to this probe"
    if check_type == "termux":
        termux_version = os.environ.get("TERMUX_VERSION")
        prefix = os.environ.get("PREFIX", "")
        in_termux = bool(termux_version) or "/com.termux/" in prefix
        if in_termux:
            return 1.0, f"Termux environment detected (TERMUX_VERSION={termux_version!r}, PREFIX={prefix!r})"
        return 0.0, (f"not running under Termux: TERMUX_VERSION unset, PREFIX={prefix!r} "
                      f"(actual platform: {platform.system()})")
    return 0.0, f"unknown check type '{check_type}'"


def probe_all(live_connectors=None):
    """live_connectors: optional list of connector names known-connected
    right now (only the calling agent can supply this -- see module
    docstring). When present, 'connector' checks resolve against it
    instead of returning the neutral 'unconfirmed' reading."""
    results = {}
    for cap in load_registry():
        check = cap["check"]
        if check.get("type") == "connector" and live_connectors is not None:
            present = check["value"] in live_connectors
            confidence, evidence = (
                (1.0, f"connector '{check['value']}' present in supplied live connector list")
                if present else
                (0.0, f"connector '{check['value']}' NOT present in supplied live connector list {sorted(live_connectors)}")
            )
        else:
            confidence, evidence = probe_one(check)
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
