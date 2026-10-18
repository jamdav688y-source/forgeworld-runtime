"""Checksummed, read-only file bundles (shared by R1 handoffs and R2a
delivery packages).

Pure file mechanics: no approval logic, no record kinds. A bundle is a
directory of files plus SHA256SUMS (the `sha256sum -c` text format). The
caller anchors sha256(SHA256SUMS) in a CXP record; check() compares what
is on disk against that anchor. Paths are relative, '/'-separated, one
level of subdirectory at most, and never contain '..'.

write() stages every file, re-reads it, makes it read-only and moves the
directory into place in one rename. Re-running with identical bytes is a
no-op (crash recovery); different bytes under the same id are refused.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

SUMS = "SHA256SUMS"
_PATH = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]{0,99}/)?[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class BundleError(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_path(path) -> bool:
    return isinstance(path, str) and bool(_PATH.match(path)) and ".." not in path


def render_sums(files: dict) -> bytes:
    """sha256sum-compatible checksum list, sorted by path."""
    return "".join(f"{sha256_hex(files[name])}  {name}\n" for name in sorted(files)).encode("ascii")


def parse_sums(data: bytes) -> dict:
    listed = {}
    for line in data.decode("ascii", "replace").splitlines():
        if "  " in line:
            digest, name = line.split("  ", 1)
            listed[name] = digest
    return listed


def read(directory: Path):
    """{relative path: bytes} for every file in the bundle, or None."""
    directory = Path(directory)
    try:
        return {p.relative_to(directory).as_posix(): p.read_bytes()
                for p in sorted(directory.rglob("*")) if p.is_file()}
    except OSError:
        return None


def write(root: Path, bundle_id: str, files: dict) -> Path:
    for name in files:
        if not valid_path(name):
            raise BundleError([f"INVALID_PATH:{name}"])
    final = Path(root) / bundle_id
    if final.exists():  # a re-run after a crash before ingest: identical bytes or refuse
        if read(final) != files:
            raise BundleError([f"BUNDLE_CONFLICT: existing bundle {bundle_id} differs"])
        return final
    staging = Path(root) / f".staging-{bundle_id}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for name, data in files.items():
            (staging / name).parent.mkdir(exist_ok=True)
            (staging / name).write_bytes(data)
        for name, data in files.items():  # re-read: what landed on disk is what was checksummed
            if (staging / name).read_bytes() != data:
                raise BundleError([f"WRITE_VERIFICATION_FAILED:{name}"])
            os.chmod(staging / name, 0o444)
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def check(present, expected: tuple, anchored_sums_sha256) -> list:
    """Integrity problems of a bundle read from disk. `expected` lists every
    file the bundle must hold (including SHA256SUMS); `anchored_sums_sha256`
    is the digest recorded in CXP, or None when no record anchors it."""
    if present is None:
        return ["BUNDLE_MISSING"]
    problems = [f"UNEXPECTED_FILE:{n}" for n in sorted(set(present) - set(expected))]
    problems += [f"FILE_MISSING:{n}" for n in expected if n not in present]
    sums = present.get(SUMS, b"")
    if anchored_sums_sha256 is not None and sha256_hex(sums) != anchored_sums_sha256:
        problems.append("CHECKSUM_LIST_NOT_ANCHORED")
    listed = parse_sums(sums)
    for name in expected:
        if name != SUMS and name in present and listed.get(name) != sha256_hex(present[name]):
            problems.append(f"FILE_TAMPERED:{name}")
    return problems
