"""Artifact-Handoff Seam: a provider-neutral, transport-neutral, parser-
neutral mechanism to acquire, validate, unpack, inventory, and route an
external artifact -- and nothing else.

MISSION: FW-ARTIFACT-HANDOFF-SEAM-001.

FLOW:

    artifact reference -> acquire -> integrity check -> content
    classification -> safe unpack if applicable -> inventory ->
    capability/parser routing -> provenance-preserving manifest

ARCHITECTURE LAW: this file contains no Gmail-, Drive-, Ryan-, or
ZIP-specific business logic. `AcquisitionProvider` is a Protocol (see
local_file_provider.py for the one adapter this mission needs to prove
the flow with local synthetic fixtures -- a future Gmail/Drive adapter is
a second file implementing the same Protocol, not a change here). Unpack
support is a dict of {content_type: unpack_fn} adapters (see
zip_unpack.py); ZIP is one entry in that dict, not the architecture --
adding tar/7z support later is "register another adapter," not "modify
this module's control flow."

REUSE LAW: identifiers are validated through evidence_envelope.
validate_mission_id (the same canonical, path-safe identifier contract
mission_id already uses -- reused, not reimplemented). Capability/parser
routing is built directly on capabilities/discover.py (load_registry,
probe_one/probe_all) and router/mission_router.py's score_capability()
(a pure function; this module never calls mission_router.route() itself,
so it never writes to the live router/decisions.jsonl operational log).

SIX INVARIANTS THIS MODULE ENFORCES STRUCTURALLY (properties, not
constructor fields -- a caller cannot construct a Manifest that claims
otherwise, mirroring the pattern local_inference/interface.py already
established for its own two invariants):

    acquisition != trust        -> trust_status        (always ACQUIRED_NOT_TRUSTED)
    extraction  != execution    -> execution_status     (always NOT_EXECUTED)
    parsing     != validation   -> validation_status    (always NOT_VALIDATED)
    artifact/model output != evidence -> evidence_status (always NOT_EVIDENCE)
    handoff     != authority    -> authority_status     (always NO_AUTHORITY_GRANTED)
    handoff     != promotion    -> promotion_status     (always NOT_PROMOTED)

FAILURE LAW: acquisition, classification, and routing never raise for an
expected failure -- they report an honest state on the Manifest (mirrors
capabilities/discover.py's UNREACHABLE/TIMEOUT vocabulary and
local_inference/interface.py's STATUS_* vocabulary). Archive extraction
fails CLOSED: if any member of an archive fails a safety check, nothing
from that archive is extracted -- not the safe members, not any of them.
Extracted content is written to a bounded, caller-owned temp location and
is never executed, imported, or invoked by this module.
"""
from __future__ import annotations

import hashlib
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from evidence_envelope import envelope  # noqa: E402 -- reused only for validate_mission_id's identifier contract
from capabilities import discover  # noqa: E402 -- reused for load_registry()/probe_all()/probe_one()
from router import mission_router  # noqa: E402 -- reused for score_capability() (pure, no side effects)

# ---------------------------------------------------------------------------
# states -- same honest, non-euphemistic vocabulary already used elsewhere
# in this repository (discover.py's UNREACHABLE/TIMEOUT; local_inference's
# STATUS_*).
# ---------------------------------------------------------------------------
ACQUISITION_PENDING = "PENDING"
ACQUISITION_ACQUIRED = "ACQUIRED"
ACQUISITION_UNREACHABLE = "UNREACHABLE"
ACQUISITION_FAILED = "FAILED"
_ACQUISITION_STATES = (ACQUISITION_PENDING, ACQUISITION_ACQUIRED, ACQUISITION_UNREACHABLE, ACQUISITION_FAILED)

EXTRACTION_NOT_APPLICABLE = "NOT_APPLICABLE"
EXTRACTION_EXTRACTED = "EXTRACTED"
EXTRACTION_REJECTED = "REJECTED"
EXTRACTION_FAILED = "FAILED"
_EXTRACTION_STATES = (EXTRACTION_NOT_APPLICABLE, EXTRACTION_EXTRACTED, EXTRACTION_REJECTED, EXTRACTION_FAILED)

SAFETY_UNKNOWN = "UNKNOWN"
SAFETY_SAFE = "SAFE"
SAFETY_UNSAFE = "UNSAFE"
SAFETY_UNSUPPORTED = "UNSUPPORTED"
_SAFETY_DISPOSITIONS = (SAFETY_UNKNOWN, SAFETY_SAFE, SAFETY_UNSAFE, SAFETY_UNSUPPORTED)

# -- fixed, non-overridable classifications every Manifest carries.
TRUST_STATUS = "ACQUIRED_NOT_TRUSTED"
EXECUTION_STATUS = "NOT_EXECUTED"
VALIDATION_STATUS = "NOT_VALIDATED"
EVIDENCE_STATUS = "NOT_EVIDENCE"
AUTHORITY_STATUS = "NO_AUTHORITY_GRANTED"
PROMOTION_STATUS = "NOT_PROMOTED"

DEFAULT_CONTENT_TYPE = "application/octet-stream"


class ArtifactHandoffError(Exception):
    """Programmer-misuse errors only (e.g. an invalid state string). Never
    raised for an expected runtime failure -- see the module docstring's
    Failure Law."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_artifact_id() -> str:
    """Generate a canonical, path-safe artifact id, reusing envelope.py's
    identifier contract rather than inventing a second one."""
    return envelope.validate_mission_id(f"ART-{uuid.uuid4().hex}")


# ---------------------------------------------------------------------------
# acquisition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactReference:
    """What the caller wants acquired. `source_provider` identifies which
    AcquisitionProvider should resolve `source_reference` -- this module
    never inspects source_reference's shape itself (a Gmail message id and
    a local file path look identical to this dataclass)."""

    source_provider: str
    source_reference: str
    declared_filename: Optional[str] = None
    declared_content_type: Optional[str] = None


@dataclass(frozen=True)
class AcquisitionOutcome:
    """What an AcquisitionProvider hands back. `data` is the raw acquired
    bytes -- this seam works on bytes only, it never assumes a specific
    transport left a file on disk."""

    state: str
    data: Optional[bytes]
    filename: Optional[str]
    declared_content_type: Optional[str]
    error_detail: Optional[str]
    evidence: str


class AcquisitionProvider(Protocol):
    """The contract every source adapter (local file, and later Gmail,
    Drive, ...) implements. Nothing in this Protocol, or in handoff()
    below, references a specific source by name."""

    provider_id: str

    def acquire(self, reference: ArtifactReference) -> AcquisitionOutcome:
        """Must not raise; must report ACQUISITION_UNREACHABLE/FAILED
        honestly instead. Must not execute, import, or interpret the
        acquired bytes in any way -- acquisition is I/O only."""
        ...


# ---------------------------------------------------------------------------
# content classification (deterministic magic-byte sniffing; no external
# `file`/libmagic dependency, so this module stays dependency-free)
# ---------------------------------------------------------------------------

_MAGIC_SIGNATURES: Sequence[tuple] = (
    (b"PK\x03\x04", "application/zip"),
    (b"PK\x05\x06", "application/zip"),  # empty zip archive
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

_EXTENSION_CONTENT_TYPES = {
    ".zip": "application/zip",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Archive-looking extensions this seam does not have an unpack adapter for.
# Detected honestly as UNSUPPORTED rather than silently treated as an
# ordinary opaque file -- "unsupported content" from the mission's archive
# defense list.
_UNSUPPORTED_ARCHIVE_EXTENSIONS = {".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"}


def detect_content_type(data: bytes) -> str:
    """Sniff the actual bytes. Never trusts a filename or a caller's
    claim -- this is the only source of `detected_content_type`."""
    for signature, content_type in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return content_type
    if not data:
        return DEFAULT_CONTENT_TYPE
    sample = data[:4096]
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return DEFAULT_CONTENT_TYPE
    if b"\x00" in sample:
        return DEFAULT_CONTENT_TYPE
    return "text/plain"


def guess_declared_content_type(filename: Optional[str], explicit_declared: Optional[str]) -> str:
    """`declared_content_type` on the manifest: whatever the source
    claimed, or (failing that) a naive extension guess -- either way,
    parsing != validation: this is a claim, not a fact."""
    if explicit_declared:
        return explicit_declared
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _EXTENSION_CONTENT_TYPES:
            return _EXTENSION_CONTENT_TYPES[suffix]
    return DEFAULT_CONTENT_TYPE


# ---------------------------------------------------------------------------
# capability/parser routing -- reuses the existing registry + router's
# pure scoring function directly, never mission_router.route() (which has
# file-write side effects this seam has no business triggering).
# ---------------------------------------------------------------------------

CONTENT_TYPE_REQUIRED_TAGS = {
    "image/png": ["ocr", "screenshot_ingestion"],
    "image/jpeg": ["ocr", "screenshot_ingestion"],
    "text/plain": ["research", "documentation"],
}


def route_to_capability(
    detected_content_type: str,
    *,
    registry: Optional[list] = None,
    reachability_state: Optional[dict] = None,
) -> tuple:
    """Return (selected_capability_id_or_None, routing_note).

    No tag mapping for this content type, or no reachable capability
    matches it -> honestly returns (None, <reason>), exactly like
    mission_router's own "queued_no_reachable_capability" outcome --
    never a forced or guessed selection.
    """
    required_tags = CONTENT_TYPE_REQUIRED_TAGS.get(detected_content_type)
    if not required_tags:
        return None, f"no capability-tag mapping registered for content type {detected_content_type!r}"

    registry = registry if registry is not None else discover.load_registry()
    reachability_state = reachability_state if reachability_state is not None else discover.probe_all()

    scored = [
        mission_router.score_capability(cap, required_tags, reachability_state, history=[])
        for cap in registry
    ]
    # Reachable AND actually tag-relevant: score_capability() blends task_fit
    # with reachability/quality/history, so a cheap, reachable-but-irrelevant
    # capability (e.g. 'git' for an image) can otherwise outscore a relevant
    # one that just happens to be unreachable. Routing must never pick an
    # irrelevant capability merely because it was available.
    candidates = [s for s in scored if s["reachable"] and s["confidence"]["task_fit"] > 0]
    if not candidates:
        return None, f"no reachable capability with a matching tag for required tags {required_tags}"
    candidates.sort(key=lambda s: s["routing_score"], reverse=True)
    best = candidates[0]
    return best["capability_id"], f"selected on routing_score={best['routing_score']} for tags {required_tags}"


# ---------------------------------------------------------------------------
# the manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Manifest:
    artifact_id: str
    parent_artifact_id: Optional[str]
    source_provider: str
    source_reference: str
    filename: Optional[str]
    declared_content_type: str
    detected_content_type: str
    size: Optional[int]
    sha256: Optional[str]
    acquisition_state: str
    extraction_state: str
    safety_disposition: str
    selected_capability: Optional[str]
    provenance_lineage: tuple
    # -- additive, non-required-minimum fields: surfaced facts, not new laws.
    content_type_mismatch: bool
    routing_note: str
    safety_findings: tuple
    error_detail: Optional[str]
    child_artifact_ids: tuple
    generated_at: str = field(default_factory=_now)

    def __post_init__(self):
        envelope.validate_mission_id(self.artifact_id)
        if self.parent_artifact_id is not None:
            envelope.validate_mission_id(self.parent_artifact_id)
        if self.acquisition_state not in _ACQUISITION_STATES:
            raise ArtifactHandoffError(f"invalid acquisition_state {self.acquisition_state!r}")
        if self.extraction_state not in _EXTRACTION_STATES:
            raise ArtifactHandoffError(f"invalid extraction_state {self.extraction_state!r}")
        if self.safety_disposition not in _SAFETY_DISPOSITIONS:
            raise ArtifactHandoffError(f"invalid safety_disposition {self.safety_disposition!r}")

    @property
    def trust_status(self) -> str:
        return TRUST_STATUS

    @property
    def execution_status(self) -> str:
        return EXECUTION_STATUS

    @property
    def validation_status(self) -> str:
        return VALIDATION_STATUS

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
            "parent_artifact_id": self.parent_artifact_id,
            "source_provider": self.source_provider,
            "source_reference": self.source_reference,
            "filename": self.filename,
            "declared_content_type": self.declared_content_type,
            "detected_content_type": self.detected_content_type,
            "size": self.size,
            "sha256": self.sha256,
            "acquisition_state": self.acquisition_state,
            "extraction_state": self.extraction_state,
            "safety_disposition": self.safety_disposition,
            "selected_capability": self.selected_capability,
            "provenance_lineage": list(self.provenance_lineage),
            "content_type_mismatch": self.content_type_mismatch,
            "routing_note": self.routing_note,
            "safety_findings": list(self.safety_findings),
            "error_detail": self.error_detail,
            "child_artifact_ids": list(self.child_artifact_ids),
            "generated_at": self.generated_at,
            "trust_status": self.trust_status,
            "execution_status": self.execution_status,
            "validation_status": self.validation_status,
            "evidence_status": self.evidence_status,
            "authority_status": self.authority_status,
            "promotion_status": self.promotion_status,
        }


# ---------------------------------------------------------------------------
# unpack adapter registry -- ZIP is one entry, not the architecture.
# ---------------------------------------------------------------------------

UnpackFn = Callable[[bytes, Any], Any]  # (data, limits) -> UnpackOutcome (see zip_unpack.UnpackOutcome shape)
UNPACK_ADAPTERS: dict = {}


def register_unpack_adapter(content_type: str, fn: UnpackFn) -> None:
    UNPACK_ADAPTERS[content_type] = fn


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def handoff(
    reference: ArtifactReference,
    acquisition_provider: AcquisitionProvider,
    *,
    parent_manifest: Optional[Manifest] = None,
    unpack_limits: Any = None,
    reachability_state: Optional[dict] = None,
    max_unpack_depth: int = 1,
    lineage_store: Any = None,
    _current_depth: int = 0,
) -> Manifest:
    """Run one artifact through the full seam and return its Manifest
    (plus, if it was a safely-unpacked archive, child Manifests reachable
    via the returned manifest.child_artifact_ids -- callers that need the
    full tree should use `handoff_tree()` below).

    `lineage_store`, when given a lineage_store.LineageStore (or anything
    exposing the same .record(dict) method), persists every manifest
    produced -- root and every descendant -- durably as it is built.
    Omitting it (the default) keeps this function's original pure,
    in-memory-only behavior; this module does not import lineage_store.py
    itself, so the dependency runs one way only (lineage_store depends on
    interface, never the reverse).
    """
    manifest, _children = _handoff_with_children(
        reference, acquisition_provider,
        parent_manifest=parent_manifest, unpack_limits=unpack_limits,
        reachability_state=reachability_state, max_unpack_depth=max_unpack_depth,
        lineage_store=lineage_store, _current_depth=_current_depth,
    )
    return manifest


def handoff_tree(
    reference: ArtifactReference,
    acquisition_provider: AcquisitionProvider,
    **kwargs,
) -> list:
    """Return [root_manifest, *all descendant manifests] in discovery order."""
    manifest, children = _handoff_with_children(reference, acquisition_provider, **kwargs)
    out = [manifest]
    out.extend(children)
    return out


def _handoff_with_children(
    reference: ArtifactReference,
    acquisition_provider: AcquisitionProvider,
    *,
    parent_manifest: Optional[Manifest] = None,
    unpack_limits: Any = None,
    reachability_state: Optional[dict] = None,
    max_unpack_depth: int = 1,
    lineage_store: Any = None,
    _current_depth: int = 0,
) -> tuple:
    artifact_id = new_artifact_id()
    parent_id = parent_manifest.artifact_id if parent_manifest is not None else None
    lineage = tuple(parent_manifest.provenance_lineage) + (parent_manifest.artifact_id,) if parent_manifest else ()

    outcome = acquisition_provider.acquire(reference)

    if outcome.state != ACQUISITION_ACQUIRED or outcome.data is None:
        manifest = Manifest(
            artifact_id=artifact_id,
            parent_artifact_id=parent_id,
            source_provider=reference.source_provider,
            source_reference=reference.source_reference,
            filename=outcome.filename or reference.declared_filename,
            declared_content_type=guess_declared_content_type(
                outcome.filename or reference.declared_filename, reference.declared_content_type
            ),
            detected_content_type=DEFAULT_CONTENT_TYPE,
            size=None,
            sha256=None,
            acquisition_state=outcome.state,
            extraction_state=EXTRACTION_NOT_APPLICABLE,
            safety_disposition=SAFETY_UNKNOWN,
            selected_capability=None,
            provenance_lineage=lineage,
            content_type_mismatch=False,
            routing_note="acquisition did not succeed; routing skipped",
            safety_findings=(),
            error_detail=outcome.error_detail,
            child_artifact_ids=(),
        )
        if lineage_store is not None:
            lineage_store.record(manifest.to_dict())
        return manifest, []

    data = outcome.data
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    filename = outcome.filename or reference.declared_filename
    declared_content_type = guess_declared_content_type(filename, outcome.declared_content_type or reference.declared_content_type)
    detected_content_type = detect_content_type(data)
    content_type_mismatch = bool(declared_content_type) and declared_content_type != detected_content_type

    safety_findings: list = []
    child_manifests: list = []

    unpack_fn = UNPACK_ADAPTERS.get(detected_content_type)
    if unpack_fn is None:
        extraction_state = EXTRACTION_NOT_APPLICABLE
        suffix = Path(filename).suffix.lower() if filename else ""
        if suffix in _UNSUPPORTED_ARCHIVE_EXTENSIONS:
            safety_disposition = SAFETY_UNSUPPORTED
            safety_findings.append(f"UNSUPPORTED_ARCHIVE_FORMAT: {suffix!r} has no registered unpack adapter")
        else:
            safety_disposition = SAFETY_SAFE
    else:
        if _current_depth >= max_unpack_depth:
            extraction_state = EXTRACTION_NOT_APPLICABLE
            safety_disposition = SAFETY_UNKNOWN
            safety_findings.append(f"NESTED_ARCHIVE_NOT_UNPACKED: max_unpack_depth={max_unpack_depth} reached")
        else:
            result = unpack_fn(data, unpack_limits)
            extraction_state = result.extraction_state
            safety_disposition = result.safety_disposition
            safety_findings.extend(result.safety_findings)
            if result.extraction_state == EXTRACTION_EXTRACTED:
                for member in result.members:
                    child_reference = ArtifactReference(
                        source_provider=reference.source_provider,
                        source_reference=f"{reference.source_reference}!{member.name}",
                        declared_filename=member.name,
                        declared_content_type=None,
                    )
                    child_provider = _StaticBytesProvider(member.name, member.data)
                    parent_stub = _ParentStub(artifact_id, lineage)
                    child_manifest, grandchildren = _handoff_with_children(
                        child_reference, child_provider,
                        parent_manifest=parent_stub, unpack_limits=unpack_limits,
                        reachability_state=reachability_state, max_unpack_depth=max_unpack_depth,
                        lineage_store=lineage_store, _current_depth=_current_depth + 1,
                    )
                    child_manifests.append(child_manifest)
                    child_manifests.extend(grandchildren)

    selected_capability, routing_note = route_to_capability(
        detected_content_type, reachability_state=reachability_state
    )

    manifest = Manifest(
        artifact_id=artifact_id,
        parent_artifact_id=parent_id,
        source_provider=reference.source_provider,
        source_reference=reference.source_reference,
        filename=filename,
        declared_content_type=declared_content_type,
        detected_content_type=detected_content_type,
        size=size,
        sha256=sha256,
        acquisition_state=outcome.state,
        extraction_state=extraction_state,
        safety_disposition=safety_disposition,
        selected_capability=selected_capability,
        provenance_lineage=lineage,
        content_type_mismatch=content_type_mismatch,
        routing_note=routing_note,
        safety_findings=tuple(safety_findings),
        error_detail=None,
        child_artifact_ids=tuple(m.artifact_id for m in child_manifests if m.parent_artifact_id == artifact_id),
    )
    if lineage_store is not None:
        lineage_store.record(manifest.to_dict())
    return manifest, child_manifests


@dataclass(frozen=True)
class _ParentStub:
    """Minimal stand-in so recursion can reuse the same
    parent_manifest-shaped access pattern without constructing a full,
    already-validated Manifest for an in-progress parent."""
    artifact_id: str
    provenance_lineage: tuple


class _StaticBytesProvider:
    """Internal-only AcquisitionProvider wrapping bytes already extracted
    from a parent archive -- child artifacts are 'acquired' from memory,
    not re-read from any external source."""

    provider_id = "extracted_member"

    def __init__(self, name: str, data: bytes):
        self._name = name
        self._data = data

    def acquire(self, reference: ArtifactReference) -> AcquisitionOutcome:
        return AcquisitionOutcome(
            state=ACQUISITION_ACQUIRED,
            data=self._data,
            filename=self._name,
            declared_content_type=None,
            error_detail=None,
            evidence="extracted from parent archive member, already in memory",
        )
