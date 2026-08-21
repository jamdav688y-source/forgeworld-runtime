#!/usr/bin/env python3
"""Capability Discovery: probes reachability of every registered capability.

Reachability is measured, not assumed. Each check type maps to a concrete
probe so the confidence score reflects what was actually observed on this
machine at this moment:
  command -> is the binary on PATH, and (when the registry declares a
             "verify" spec) does it actually launch, identify itself as the
             required tool, and meet a minimum version?
  env     -> is the credential/env var present
  network -> can we open a TCP connection to the service
  self    -> the capability is this runtime itself (always reachable)
  manual  -> cannot be probed statically; operator must confirm (neutral 0.5)

Command verification levels (returned as "evidence_level" for command
checks only): PATH_FOUND, LAUNCH_VERIFIED, IDENTITY_VERIFIED,
VERSION_VERIFIED, UNREACHABLE, TIMEOUT, IDENTITY_MISMATCH.

A registry command check without a "verify" spec keeps the original,
weaker path-only behavior (PATH_FOUND) unchanged -- not every command
supports a safe, universal probe like "--version", so probing deeper is
opt-in per capability, not assumed.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "registry.json"
STATE_PATH = ROOT / "state.json"

DEFAULT_VERIFY_ARGS = ["--version"]
DEFAULT_VERIFY_TIMEOUT_SECONDS = 5


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)["capabilities"]


def _parse_version(text):
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch or 0))


def _probe_resolved(path, verify_spec):
    """Verify an already-resolved executable path against a verify spec.

    Isolated from PATH lookup so it can be exercised directly in tests
    against a known executable, independent of shutil.which/PATH state.
    """
    args = verify_spec.get("args", DEFAULT_VERIFY_ARGS)
    timeout = verify_spec.get("timeout_seconds", DEFAULT_VERIFY_TIMEOUT_SECONDS)

    try:
        proc = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 0.0, "TIMEOUT", f"'{path}' did not respond within {timeout}s"
    except OSError as exc:
        return 0.0, "UNREACHABLE", f"'{path}' failed to launch: {exc}"

    output = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()

    if proc.returncode != 0:
        return 0.0, "UNREACHABLE", (
            f"'{path}' exited {proc.returncode} (not a working executable): {output[:200]!r}"
        )

    identity_pattern = verify_spec.get("expect_identity")
    if not identity_pattern:
        return 1.0, "LAUNCH_VERIFIED", (
            f"'{path}' launched and exited 0; no identity pattern declared "
            f"to confirm which tool this is: {output[:200]!r}"
        )

    if not re.search(identity_pattern, output):
        return 0.0, "IDENTITY_MISMATCH", (
            f"'{path}' launched but output did not match expected identity "
            f"pattern {identity_pattern!r}: {output[:200]!r}"
        )

    min_version = verify_spec.get("min_version")
    if not min_version:
        return 1.0, "IDENTITY_VERIFIED", (
            f"'{path}' identity confirmed via {identity_pattern!r}: {output[:200]!r}"
        )

    found_version = _parse_version(output)
    min_version_tuple = _parse_version(min_version)
    if found_version is None:
        return 1.0, "IDENTITY_VERIFIED", (
            f"'{path}' identity confirmed but no version number could be parsed "
            f"from output to check against minimum {min_version}: {output[:200]!r}"
        )
    if found_version < min_version_tuple:
        return 0.0, "IDENTITY_VERIFIED", (
            f"'{path}' identity confirmed but version {found_version} is below "
            f"required minimum {min_version_tuple}: {output[:200]!r}"
        )
    return 1.0, "VERSION_VERIFIED", (
        f"'{path}' identity confirmed via {identity_pattern!r}, version "
        f"{found_version} satisfies minimum {min_version_tuple}: {output[:200]!r}"
    )


def _verify_command(value, verify_spec):
    path = shutil.which(value)
    if path is None:
        return 0.0, "UNREACHABLE", f"command '{value}' not found on PATH"

    if not verify_spec:
        return 1.0, "PATH_FOUND", (
            f"command '{value}' found on PATH at '{path}' "
            "(path-only check; no executable probe declared for this capability)"
        )

    return _probe_resolved(path, verify_spec)


def probe_one(check):
    check_type = check.get("type")
    if check_type == "command":
        confidence, level, evidence = _verify_command(check["value"], check.get("verify"))
        return confidence, evidence, level
    if check_type == "env":
        present = bool(os.environ.get(check["value"]))
        return (1.0 if present else 0.0), f"env var '{check['value']}' {'set' if present else 'unset'}", None
    if check_type == "network":
        host, _, port = check["value"].partition(":")
        try:
            socket.create_connection((host, int(port)), timeout=2).close()
            return 1.0, f"TCP connect to {check['value']} succeeded", None
        except OSError as e:
            return 0.0, f"TCP connect to {check['value']} failed: {e}", None
    if check_type == "self":
        return 1.0, "capability is the local runtime itself", None
    if check_type == "manual":
        return 0.5, "static probe not possible; requires operator/runtime confirmation", None
    return 0.0, f"unknown check type '{check_type}'", None


def probe_all():
    results = {}
    for cap in load_registry():
        confidence, evidence, level = probe_one(cap["check"])
        entry = {
            "reachability_confidence": confidence,
            "evidence": evidence,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if level is not None:
            entry["evidence_level"] = level
        results[cap["id"]] = entry
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
