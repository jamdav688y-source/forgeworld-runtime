"""Universal Content Readers: a provider-neutral contract that turns an
already-acquired artifact's bytes into structured, bounded content --
and nothing else.

MISSION: FW-UNIVERSAL-CONTENT-READERS-001 (FW-PERMANENT-OFFLINE-SUBSTRATE-001,
Microphase 02).

SCOPE BOUNDARY: this module reads. It does not interpret, does not
verify, and does not decide what content means. A reader that
successfully parses JSON has proven the bytes are syntactically valid
JSON -- nothing about whether the *data* is true, current, or
authoritative. See the seven fixed properties on ContentReadResult below.

ARCHITECTURE: readers are capabilities behind one stable contract
(ContentReader Protocol + a {content_type: reader} registry), mirroring
artifact_handoff.interface.UNPACK_ADAPTERS exactly -- one dict lookup,
not one giant conditional. text_readers.py / html_reader.py /
image_metadata_reader.py / archive_reader.py each register themselves as
an import side effect, the same pattern zip_unpack.py already
established for artifact_handoff.

DEPENDENCY DIRECTION: this module does not import artifact_handoff.
build_request_from_manifest() accepts a plain dict shaped like
Manifest.to_dict() (duck-typed), not the Manifest class itself, so
content_readers stays usable standalone and the dependency runs one way
only: a caller that already has both modules wires them together (see
the tests), neither module needs to know the other exists.

REUSE: no new duplicate JSON/CSV/HTML parser is written where the
standard library already provides a safe one (json, csv, html.parser).
YAML uses PyYAML's yaml.safe_load exclusively -- never yaml.load with a
non-safe Loader -- because this module's job is to read data, never to
construct arbitrary Python objects from untrusted input. Archive content
is never re-parsed here: archive_reader.py reuses artifact_handoff's
already-computed child manifests (see ARCHIVE INVENTORY below).

SAFETY LAW: no reader here ever calls exec/eval on read content, never
imports a file being inspected, and never evaluates JSON/YAML/source
code as code -- reading is I/O plus a safe structural parser, nothing
executes. Every reader is bounded by ReadLimits before it does
non-trivial work. No reader makes a network call.

SEVEN INVARIANTS THIS MODULE ENFORCES STRUCTURALLY (properties, not
constructor fields, exactly like artifact_handoff.interface.Manifest and
local_inference.interface.InferenceResult before it -- a caller cannot
construct a ContentReadResult that claims otherwise):

    reading != interpretation      -> interpretation_status (NOT_INTERPRETED)
    reading != verification        -> verification_status   (NOT_VERIFIED)
    metadata extraction != trust   -> trust_status           (EXTRACTED_NOT_TRUSTED)
    parser success != content truth -> truth_status          (PARSER_SUCCESS_NOT_TRUTH)
    reading != evidence promotion  -> evidence_status        (NOT_EVIDENCE)
                                    -> promotion_status       (NOT_PROMOTED)
    reading != authority           -> authority_status       (NO_AUTHORITY_GRANTED)

FAILURE LAW: unsupported != guessed. A content type with no registered
reader is reported UNSUPPORTED with an honest reason -- never routed to
the "closest" reader as a guess. truncation must be explicit: truncation
is its own boolean field plus a human-readable reason, never silently
folded into a generic status.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

READ_OK = "READ"
READ_UNSUPPORTED = "UNSUPPORTED"
READ_MALFORMED = "MALFORMED"
READ_FAILED = "FAILED"
_STATUSES = (READ_OK, READ_UNSUPPORTED, READ_MALFORMED, READ_FAILED)

# -- fixed, non-overridable classifications every ContentReadResult carries.
INTERPRETATION_STATUS = "NOT_INTERPRETED"
VERIFICATION_STATUS = "NOT_VERIFIED"
TRUST_STATUS = "EXTRACTED_NOT_TRUSTED"
TRUTH_STATUS = "PARSER_SUCCESS_NOT_TRUTH"
EVIDENCE_STATUS = "NOT_EVIDENCE"
AUTHORITY_STATUS = "NO_AUTHORITY_GRANTED"
PROMOTION_STATUS = "NOT_PROMOTED"

PDF_SIGNATURE = b"%PDF-"
PDF_UNSUPPORTED_REASON = (
    "no safe local PDF parser is installed in this environment "
    "(pypdf/pdfminer.six/PyMuPDF not found); PDF reading is honestly "
    "unsupported rather than attempted with an unsafe or partial parser. "
    "Recorded dependency gap -- nothing was installed to close it."
)


class ContentReaderError(Exception):
    """Programmer-misuse errors only (e.g. an invalid status string).
    Never raised for an expected runtime failure -- see the Failure Law."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class ReadLimits:
    max_input_bytes: int = 5 * 1024 * 1024
    max_output_chars: int = 200_000
    max_csv_rows: int = 10_000
    max_json_yaml_bytes: int = 2 * 1024 * 1024
    max_links: int = 200


DEFAULT_LIMITS = ReadLimits()


@dataclass(frozen=True)
class ContentReadRequest:
    artifact_id: str
    data: bytes
    detected_content_type: str
    declared_content_type: Optional[str] = None
    filename: Optional[str] = None
    reader_hint: Optional[str] = None
    limits: ReadLimits = field(default_factory=lambda: DEFAULT_LIMITS)
    source_sha256: Optional[str] = None
    child_manifests: tuple = ()  # tuple of dicts shaped like Manifest.to_dict(), when this artifact is an archive


@dataclass(frozen=True)
class ContentReadResult:
    artifact_id: str
    reader_id: str
    reader_version: str
    content_type: str
    status: str
    structured_content: Any
    text_content: Optional[str]
    metadata: dict
    provenance_reference: str
    warnings: tuple
    errors: tuple
    truncated: bool
    truncation_detail: Optional[str] = None
    source_sha256: Optional[str] = None
    generated_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.status not in _STATUSES:
            raise ContentReaderError(f"status {self.status!r} is not one of {_STATUSES}")
        if self.status == READ_OK and self.truncated and not self.truncation_detail:
            raise ContentReaderError("truncated=True requires a non-empty truncation_detail")

    @property
    def interpretation_status(self) -> str:
        return INTERPRETATION_STATUS

    @property
    def verification_status(self) -> str:
        return VERIFICATION_STATUS

    @property
    def trust_status(self) -> str:
        return TRUST_STATUS

    @property
    def truth_status(self) -> str:
        return TRUTH_STATUS

    @property
    def evidence_status(self) -> str:
        return EVIDENCE_STATUS

    @property
    def authority_status(self) -> str:
        return AUTHORITY_STATUS

    @property
    def promotion_status(self) -> str:
        return PROMOTION_STATUS

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "reader_id": self.reader_id,
            "reader_version": self.reader_version,
            "content_type": self.content_type,
            "status": self.status,
            "structured_content": self.structured_content,
            "text_content": self.text_content,
            "metadata": self.metadata,
            "provenance_reference": self.provenance_reference,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "truncated": self.truncated,
            "truncation_detail": self.truncation_detail,
            "source_sha256": self.source_sha256,
            "generated_at": self.generated_at,
            "interpretation_status": self.interpretation_status,
            "verification_status": self.verification_status,
            "trust_status": self.trust_status,
            "truth_status": self.truth_status,
            "evidence_status": self.evidence_status,
            "authority_status": self.authority_status,
            "promotion_status": self.promotion_status,
        }


class ContentReader(Protocol):
    """The contract every reader (plain text, JSON, YAML, CSV, HTML,
    source code, image metadata, archive inventory, and later formats)
    implements. Nothing in this Protocol, or in read_content() below,
    references a specific format by name."""

    reader_id: str
    reader_version: str

    def read(self, request: ContentReadRequest) -> ContentReadResult:
        """Must not raise for an expected failure (malformed content,
        unsupported sub-case); report READ_MALFORMED/READ_FAILED honestly
        instead. Must never exec/eval/import the content it reads."""
        ...


READERS: dict = {}


def register_reader(content_type: str, reader: ContentReader) -> None:
    READERS[content_type] = reader


# ---------------------------------------------------------------------------
# reader-selection sub-classification for the text/plain bucket
# ---------------------------------------------------------------------------

_FILENAME_SUFFIX_READER_TYPES = {
    ".md": "text/markdown", ".markdown": "text/markdown",
    ".json": "application/json",
    ".yaml": "application/yaml", ".yml": "application/yaml",
    ".csv": "text/csv",
    ".html": "text/html", ".htm": "text/html",
    ".py": "text/x-source-code", ".js": "text/x-source-code", ".ts": "text/x-source-code",
    ".go": "text/x-source-code", ".rs": "text/x-source-code", ".java": "text/x-source-code",
    ".c": "text/x-source-code", ".cpp": "text/x-source-code", ".h": "text/x-source-code",
    ".rb": "text/x-source-code", ".sh": "text/x-source-code", ".php": "text/x-source-code",
}


def classify_reader_content_type(data: bytes, filename: Optional[str]) -> str:
    """Choose which registered reader to try within the text/plain
    bucket. Filename extension is ONE hint among several, never the sole
    or final arbiter -- the chosen reader still independently validates
    the actual bytes and reports READ_MALFORMED honestly if they don't
    match (see text_readers.JSONReader for the concrete case this
    protects: a mismatch is surfaced, never silently accepted).
    """
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _FILENAME_SUFFIX_READER_TYPES:
            return _FILENAME_SUFFIX_READER_TYPES[suffix]

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "text/plain"

    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            json.loads(text)
            return "application/json"
        except ValueError:
            pass

    lowered = stripped[:200].lower()
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        return "text/html"

    return "text/plain"


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def _unsupported(request: ContentReadRequest, reason: str, content_type: Optional[str] = None) -> ContentReadResult:
    return ContentReadResult(
        artifact_id=request.artifact_id, reader_id="none", reader_version="n/a",
        content_type=content_type or request.detected_content_type, status=READ_UNSUPPORTED,
        structured_content=None, text_content=None, metadata={},
        provenance_reference=request.artifact_id, warnings=(), errors=(reason,),
        truncated=False, source_sha256=request.source_sha256,
    )


def _failed(request: ContentReadRequest, reason: str, content_type: Optional[str] = None, truncated: bool = False) -> ContentReadResult:
    return ContentReadResult(
        artifact_id=request.artifact_id, reader_id="none", reader_version="n/a",
        content_type=content_type or request.detected_content_type, status=READ_FAILED,
        structured_content=None, text_content=None, metadata={},
        provenance_reference=request.artifact_id, warnings=(), errors=(reason,),
        truncated=truncated, truncation_detail=reason if truncated else None,
        source_sha256=request.source_sha256,
    )


def read_content(request: ContentReadRequest) -> ContentReadResult:
    """Select a reader based on declared/detected content and capability
    availability -- never filename alone -- and invoke it. Never raises
    for an expected failure; an unexpected exception from a reader
    implementation is itself caught and reported as READ_FAILED rather
    than propagated, so a single broken reader can never look like
    something scarier than "this reader failed."
    """
    if len(request.data) > request.limits.max_input_bytes:
        return _failed(
            request,
            f"input size {len(request.data)} bytes exceeds max_input_bytes limit "
            f"{request.limits.max_input_bytes}; refusing to parse",
            truncated=True,
        )

    # PDF is checked unconditionally, ahead of everything else: a minimal,
    # all-ASCII synthetic PDF can otherwise decode as valid UTF-8 text and
    # be misrouted to the plain-text reader. The %PDF- signature is
    # unambiguous, so it always wins regardless of what detected_content_type
    # says, and regardless of any reader_hint (a hint cannot make an
    # unsupported format supported).
    if request.data.startswith(PDF_SIGNATURE):
        return _unsupported(request, PDF_UNSUPPORTED_REASON, "application/pdf")

    if request.reader_hint:
        reader = READERS.get(request.reader_hint)
        if reader is None:
            return _unsupported(request, f"reader_hint {request.reader_hint!r} is not a registered reader", request.reader_hint)
        return _safe_invoke(reader, request, request.reader_hint)

    if request.detected_content_type not in ("text/plain", "application/zip", "image/png", "image/jpeg"):
        return _unsupported(
            request, f"no reader for content type {request.detected_content_type!r}", request.detected_content_type
        )

    if request.detected_content_type == "text/plain":
        content_type = classify_reader_content_type(request.data, request.filename)
    else:
        content_type = request.detected_content_type

    reader = READERS.get(content_type)
    if reader is None:
        return _unsupported(request, f"no reader registered for content type {content_type!r}", content_type)
    return _safe_invoke(reader, request, content_type)


def _safe_invoke(reader: ContentReader, request: ContentReadRequest, content_type: str) -> ContentReadResult:
    try:
        result = reader.read(request)
    except Exception as exc:  # noqa: BLE001 -- converted to an honest FAILED result, never propagated
        return ContentReadResult(
            artifact_id=request.artifact_id, reader_id=getattr(reader, "reader_id", "unknown"),
            reader_version=getattr(reader, "reader_version", "unknown"), content_type=content_type,
            status=READ_FAILED, structured_content=None, text_content=None,
            metadata={}, provenance_reference=request.artifact_id, warnings=(),
            errors=(f"reader raised an unexpected exception: {exc!r}",), truncated=False,
            source_sha256=request.source_sha256,
        )
    if result.artifact_id != request.artifact_id:
        raise ContentReaderError(
            f"reader {reader.reader_id!r} returned a result for a different artifact_id "
            f"({result.artifact_id!r} != {request.artifact_id!r})"
        )
    return result


# ---------------------------------------------------------------------------
# artifact_handoff glue -- duck-typed on Manifest.to_dict()'s shape, no import
# ---------------------------------------------------------------------------

def build_request_from_manifest(
    manifest_dict: dict,
    data: bytes,
    *,
    child_manifest_dicts: tuple = (),
    limits: Optional[ReadLimits] = None,
    reader_hint: Optional[str] = None,
) -> ContentReadRequest:
    """Build a ContentReadRequest from an artifact_handoff Manifest's
    to_dict() output plus its already-acquired bytes. This is the
    'artifact -> reader selection -> ContentReadResult' path the
    architecture requires, without content_readers importing
    artifact_handoff or gaining any authority over the artifact: it only
    reads fields already present on the dict."""
    return ContentReadRequest(
        artifact_id=manifest_dict["artifact_id"],
        data=data,
        detected_content_type=manifest_dict["detected_content_type"],
        declared_content_type=manifest_dict.get("declared_content_type"),
        filename=manifest_dict.get("filename"),
        reader_hint=reader_hint,
        limits=limits or DEFAULT_LIMITS,
        source_sha256=manifest_dict.get("sha256"),
        child_manifests=tuple(child_manifest_dicts),
    )
