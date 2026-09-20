"""ZIP unpack adapter: ONE case registered under interface.UNPACK_ADAPTERS,
not the architecture. All ZIP-specific code lives here; interface.py only
knows "there may be a function registered for this content type."

SAFETY: fails CLOSED. If any member of the archive fails any check, the
whole archive is rejected -- not the unsafe members, ALL of them. Members
are validated entirely from zip central-directory metadata (name,
external_attr, compress_size, file_size) BEFORE any bytes are
decompressed, so an expansion-bomb member is caught without ever being
expanded.

Extracted content is returned as in-memory bytes (ExtractedMember), never
written to an arbitrary filesystem path -- this structurally removes the
classic zip-slip *write* risk (there is no `extractall()` and no path
this module writes to) while the path-safety checks still validate that
the archive *would* be safe if a caller later chose to materialize it.
Nothing extracted here is ever executed, imported, or invoked.
"""
from __future__ import annotations

import io
import re
import stat
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from artifact_handoff import interface as _interface  # noqa: E402

EXTRACTION_NOT_APPLICABLE = _interface.EXTRACTION_NOT_APPLICABLE
EXTRACTION_EXTRACTED = _interface.EXTRACTION_EXTRACTED
EXTRACTION_REJECTED = _interface.EXTRACTION_REJECTED
EXTRACTION_FAILED = _interface.EXTRACTION_FAILED
SAFETY_SAFE = _interface.SAFETY_SAFE
SAFETY_UNSAFE = _interface.SAFETY_UNSAFE

_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class UnpackLimits:
    max_path_depth: int = 12
    max_member_uncompressed_bytes: int = 20 * 1024 * 1024
    max_total_uncompressed_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: int = 100
    max_member_count: int = 1000


DEFAULT_LIMITS = UnpackLimits()


@dataclass(frozen=True)
class ExtractedMember:
    name: str
    data: bytes


@dataclass(frozen=True)
class UnpackOutcome:
    extraction_state: str
    safety_disposition: str
    safety_findings: tuple
    members: List[ExtractedMember] = field(default_factory=list)


def _is_unsafe_member_name(name: str) -> Optional[str]:
    if not name:
        return "EMPTY_MEMBER_NAME"
    if "\x00" in name:
        return "NUL_BYTE_IN_NAME"
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return "ABSOLUTE_PATH"
    if _DRIVE_LETTER_RE.match(normalized):
        return "ABSOLUTE_PATH"
    if ".." in normalized.split("/"):
        return "PATH_TRAVERSAL"
    return None


def _member_depth(name: str) -> int:
    normalized = name.replace("\\", "/").strip("/")
    return normalized.count("/")


def _is_symlink(zi: zipfile.ZipInfo) -> bool:
    mode = (zi.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def safe_unpack_zip(data: bytes, limits: Optional[UnpackLimits] = None) -> UnpackOutcome:
    limits = limits or DEFAULT_LIMITS

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infolist = zf.infolist()
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        return UnpackOutcome(
            extraction_state=EXTRACTION_FAILED,
            safety_disposition=SAFETY_UNSAFE,
            safety_findings=(f"MALFORMED_ARCHIVE: {exc}",),
        )

    if len(infolist) > limits.max_member_count:
        return UnpackOutcome(
            extraction_state=EXTRACTION_REJECTED,
            safety_disposition=SAFETY_UNSAFE,
            safety_findings=(f"EXPANSION_BOMB: {len(infolist)} members exceeds limit {limits.max_member_count}",),
        )

    findings: List[str] = []
    total_uncompressed = 0

    for zi in infolist:
        reason = _is_unsafe_member_name(zi.filename)
        if reason:
            findings.append(f"{reason}: {zi.filename!r}")
            continue
        if _member_depth(zi.filename) > limits.max_path_depth:
            findings.append(f"EXCESSIVE_NESTING: {zi.filename!r} exceeds depth {limits.max_path_depth}")
            continue
        if _is_symlink(zi):
            findings.append(f"UNSAFE_LINK: {zi.filename!r} is a symlink entry")
            continue

        total_uncompressed += zi.file_size
        if zi.file_size > limits.max_member_uncompressed_bytes:
            findings.append(
                f"EXPANSION_BOMB: {zi.filename!r} uncompressed size {zi.file_size} "
                f"exceeds member limit {limits.max_member_uncompressed_bytes}"
            )
            continue
        if zi.compress_size > 0:
            ratio = zi.file_size / zi.compress_size
            if ratio > limits.max_compression_ratio:
                findings.append(
                    f"EXPANSION_BOMB: {zi.filename!r} compression ratio {ratio:.1f} "
                    f"exceeds limit {limits.max_compression_ratio}"
                )
                continue

    if total_uncompressed > limits.max_total_uncompressed_bytes:
        findings.append(
            f"EXPANSION_BOMB: total uncompressed size {total_uncompressed} "
            f"exceeds archive limit {limits.max_total_uncompressed_bytes}"
        )

    if findings:
        return UnpackOutcome(
            extraction_state=EXTRACTION_REJECTED,
            safety_disposition=SAFETY_UNSAFE,
            safety_findings=tuple(findings),
        )

    members = []
    for zi in infolist:
        if zi.filename.endswith("/"):
            continue  # directory entry: validated above, nothing to extract
        members.append(ExtractedMember(name=zi.filename, data=zf.read(zi)))

    return UnpackOutcome(
        extraction_state=EXTRACTION_EXTRACTED,
        safety_disposition=SAFETY_SAFE,
        safety_findings=(),
        members=members,
    )


_interface.register_unpack_adapter("application/zip", safe_unpack_zip)
