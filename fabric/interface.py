"""Two-Node Fabric Contract: the smallest provider-neutral, transport-
neutral representation of two ForgeWorld nodes (PC_NODE, PHONE_NODE)
exchanging an artifact and a capability result.

MISSION: FW-TWO-NODE-FABRIC-CONTRACT-001.

ARCHITECTURE LAW: transport is an adapter, not the architecture. Nothing
in this file imports socket/http/ssh/bluetooth/usb, references an IP
address, or assumes any single networking technology. `FabricTransport`
is a Protocol; `fabric/transports.py`'s InMemoryFabricTransport is ONE
adapter, proven here so the contract can be tested with no network, no
phone, and no external service. A future LAN/Tailscale/SSH/HTTP adapter
is a second file implementing the same Protocol -- this module does not
change. The same is true of inference (Ollama is an adapter to
local_inference, not the architecture) and of capabilities (whatever
invokes a capability here is an adapter to this Protocol, not the
architecture) -- ForgeWorld survives replacement of all of them.

REUSE LAW: this module sits ON TOP of already-built substrate, not beside
it. Node/envelope/receipt identifiers are validated through
evidence_envelope.validate_mission_id (the same canonical, path-safe
identifier contract used everywhere else in this program). When an
envelope's payload is accepted at a destination node, it is run through
the REAL artifact_handoff.interface.handoff() pipeline (classification,
safety disposition, routing, durable lineage via whatever LineageStore
the caller supplies) -- this module does not reclassify or re-hash
content that artifact_handoff already knows how to handle. Nothing here
duplicates zip_unpack.py, content_readers, or local_inference; a fabric
capability provider (fabric/capabilities.py) is a thin adapter that
calls into that existing machinery.

AUTHORITY LAW: node possession of an artifact/envelope never implies
execution authority. `AuthorityContext` is an explicit, scoped grant
(actor_id + an allowlist of capability_ids); `authority_permits()` is
the one and only gate a RemoteCapabilityRequest passes through before a
capability is invoked. The phone is never given an unrestricted grant by
anything in this module -- callers construct the AuthorityContext they
actually want to test, and an empty or narrow allowlist is what "the
phone is a capture/intake/review node, not an unrestricted remote
execution client" looks like structurally.

SIX INVARIANTS THIS MODULE ENFORCES STRUCTURALLY (properties, not
constructor fields, exactly like every other contract in this program --
a caller cannot construct a result object that claims otherwise):

    transfer != trust                    -> TransferResult.trust_status
    receipt != truth                     -> FabricReceipt.truth_status
    model output != evidence             -> RemoteCapabilityResult.evidence_status,
                                             FabricReceipt.evidence_status
    successful execution != promotion    -> RemoteCapabilityResult.promotion_status,
                                             FabricReceipt.promotion_status
    node possession != execution authority -> TransferResult.possession_status,
                                             RemoteCapabilityResult.possession_status,
                                             FabricReceipt.possession_status

("retrieval != authority" is preserved by omission: this module performs
no retrieval and grants no authority from one, so there is nothing here
that could violate it -- see FW-OFFLINE-RETRIEVAL-SUBSTRATE-001, not yet
started, for where that invariant will next become load-bearing.)

FAILURE LAW: every orchestration function here returns a structured
result with an honest state for unreachable node / malformed envelope /
hash mismatch / unsupported capability / unauthorized request /
duplicate artifact / incomplete result / transport failure -- never
raises for any of these expected conditions, and never silently
substitutes, retries, or guesses.
"""
from __future__ import annotations

import hashlib
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from evidence_envelope import envelope  # noqa: E402 -- validate_mission_id / InvalidMissionIdError only
from artifact_handoff import interface as ah_interface  # noqa: E402 -- handoff()/ArtifactReference/AcquisitionOutcome reuse

# ---------------------------------------------------------------------------
# node identity
# ---------------------------------------------------------------------------

NODE_TYPE_PC = "PC_NODE"
NODE_TYPE_PHONE = "PHONE_NODE"
NODE_TYPES = (NODE_TYPE_PC, NODE_TYPE_PHONE)

LOCALITY_LOCAL_ONLY = "local_only"


class FabricError(Exception):
    """Programmer-misuse errors only (e.g. an invalid state string, an
    inconsistent envelope/request construction). Never raised for an
    expected runtime failure -- see the module docstring's Failure Law."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str) -> str:
    return envelope.validate_mission_id(f"{prefix}-{uuid.uuid4().hex}")


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    node_type: str
    display_name: str
    locality: str = LOCALITY_LOCAL_ONLY
    registered_at: str = field(default_factory=_now)

    def __post_init__(self):
        envelope.validate_mission_id(self.node_id)
        if self.node_type not in NODE_TYPES:
            raise FabricError(f"node_type {self.node_type!r} is not one of {NODE_TYPES}")


@dataclass(frozen=True)
class NodeCapabilityAdvertisement:
    """What a node tells the fabric it can do. Advertising a capability
    is not the same as authorizing anyone to invoke it -- see
    AuthorityContext."""

    node_id: str
    capability_id: str
    tags: tuple = ()
    reachable: bool = True
    advertised_at: str = field(default_factory=_now)


@dataclass(frozen=True)
class AuthorityContext:
    """An explicit, scoped grant: actor_id may request exactly the
    capability_ids in granted_capability_ids, nothing more. An empty
    tuple grants nothing -- there is no wildcard, and nothing in this
    module can widen a grant after construction."""

    actor_id: str
    granted_capability_ids: tuple
    granted_by: str
    granted_at: str = field(default_factory=_now)
    expires_at: Optional[str] = None  # structural placeholder only; time-based expiry evaluation is NOT implemented in this mission


def authority_permits(context: AuthorityContext, capability_id: str) -> bool:
    return capability_id in context.granted_capability_ids


# ---------------------------------------------------------------------------
# artifact envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactEnvelope:
    envelope_id: str
    artifact_id: str
    source_node_id: str
    payload: bytes
    sha256: str
    size: int
    declared_content_type: Optional[str]
    provenance_lineage: tuple = ()
    created_at: str = field(default_factory=_now)


def build_artifact_envelope(
    source_node_id: str, payload: bytes, *, declared_content_type: Optional[str] = None,
    artifact_id: Optional[str] = None, provenance_lineage: tuple = (),
) -> ArtifactEnvelope:
    """Reuses artifact_handoff's identifier contract for artifact_id
    (via new_artifact_id()) rather than minting a second one."""
    return ArtifactEnvelope(
        envelope_id=_new_id("ENV"),
        artifact_id=artifact_id or ah_interface.new_artifact_id(),
        source_node_id=source_node_id,
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        declared_content_type=declared_content_type,
        provenance_lineage=provenance_lineage,
    )


def validate_envelope(env: ArtifactEnvelope) -> Optional[str]:
    """Returns an error message if `env` is malformed, else None. Never
    raises."""
    try:
        envelope.validate_mission_id(env.envelope_id)
        envelope.validate_mission_id(env.artifact_id)
        envelope.validate_mission_id(env.source_node_id)
    except envelope.InvalidMissionIdError as exc:
        return f"envelope identity invalid: {exc}"
    if not isinstance(env.payload, (bytes, bytearray)):
        return "payload must be bytes"
    if not isinstance(env.sha256, str) or len(env.sha256) != 64 or any(c not in "0123456789abcdef" for c in env.sha256.lower()):
        return "sha256 must be a 64-character hex string"
    if env.size != len(env.payload):
        return f"declared size {env.size} does not match actual payload length {len(env.payload)}"
    computed = hashlib.sha256(bytes(env.payload)).hexdigest()
    if computed.lower() != env.sha256.lower():
        return f"hash mismatch: envelope declares sha256={env.sha256} but payload actually hashes to {computed}"
    return None


# ---------------------------------------------------------------------------
# transfer
# ---------------------------------------------------------------------------

TRANSFER_PENDING = "PENDING"
TRANSFER_COMPLETED = "COMPLETED"
TRANSFER_REJECTED = "REJECTED"
TRANSFER_UNREACHABLE = "UNREACHABLE"
TRANSFER_FAILED = "FAILED"
_TRANSFER_STATES = (TRANSFER_PENDING, TRANSFER_COMPLETED, TRANSFER_REJECTED, TRANSFER_UNREACHABLE, TRANSFER_FAILED)

POSSESSION_STATUS = "POSSESSION_GRANTS_NO_AUTHORITY"
TRUST_STATUS = "TRANSFERRED_NOT_TRUSTED"


@dataclass(frozen=True)
class TransferRequest:
    request_id: str
    envelope: ArtifactEnvelope
    source_node_id: str
    destination_node_id: str
    authority_context: AuthorityContext
    correlation_id: str
    requested_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.source_node_id != self.envelope.source_node_id:
            raise FabricError(
                f"TransferRequest.source_node_id {self.source_node_id!r} does not match "
                f"envelope.source_node_id {self.envelope.source_node_id!r}"
            )


@dataclass(frozen=True)
class TransferResult:
    request_id: str
    transfer_id: str
    source_node_id: str
    destination_node_id: str
    transfer_state: str
    integrity_verified: bool
    error_detail: Optional[str]
    correlation_id: str
    completed_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.transfer_state not in _TRANSFER_STATES:
            raise FabricError(f"transfer_state {self.transfer_state!r} is not one of {_TRANSFER_STATES}")

    @property
    def trust_status(self) -> str:
        return TRUST_STATUS

    @property
    def possession_status(self) -> str:
        return POSSESSION_STATUS


class FabricTransport(Protocol):
    """The contract every transport adapter (in-memory now; LAN/SSH/
    HTTP/Tailscale/Bluetooth/USB/cloud-relay later) implements. Nothing
    in submit_transfer() below references a specific transport by name."""

    transport_id: str

    def deliver(self, destination_node_id: str, env: ArtifactEnvelope) -> dict:
        """Return {"delivered": bool, "reason": str}. Must not raise for
        an unreachable destination -- report it in the returned dict."""
        ...

    def pull(self, node_id: str) -> list:
        """Return (and clear) the list of ArtifactEnvelope waiting for
        node_id."""
        ...


def submit_transfer(request: TransferRequest, transport: FabricTransport) -> TransferResult:
    """PHONE_NODE (or any source) -> FABRIC: validate, verify integrity,
    hand off to a transport adapter. Never raises for an expected
    failure; an unexpected transport exception is itself caught and
    reported as TRANSFER_FAILED."""
    transfer_id = _new_id("XFER")

    reason = validate_envelope(request.envelope)
    if reason is not None:
        return TransferResult(
            request_id=request.request_id, transfer_id=transfer_id,
            source_node_id=request.source_node_id, destination_node_id=request.destination_node_id,
            transfer_state=TRANSFER_REJECTED, integrity_verified=False, error_detail=reason,
            correlation_id=request.correlation_id,
        )

    try:
        outcome = transport.deliver(request.destination_node_id, request.envelope)
    except Exception as exc:  # noqa: BLE001 -- converted to an honest FAILED result, never propagated
        return TransferResult(
            request_id=request.request_id, transfer_id=transfer_id,
            source_node_id=request.source_node_id, destination_node_id=request.destination_node_id,
            transfer_state=TRANSFER_FAILED, integrity_verified=True,
            error_detail=f"transport {getattr(transport, 'transport_id', 'unknown')!r} raised an unexpected exception: {exc!r}",
            correlation_id=request.correlation_id,
        )

    if not outcome.get("delivered"):
        reason_text = outcome.get("reason", "delivery failed for an unspecified reason")
        state = TRANSFER_UNREACHABLE if "not reachable" in reason_text.lower() else TRANSFER_FAILED
        return TransferResult(
            request_id=request.request_id, transfer_id=transfer_id,
            source_node_id=request.source_node_id, destination_node_id=request.destination_node_id,
            transfer_state=state, integrity_verified=True, error_detail=reason_text,
            correlation_id=request.correlation_id,
        )

    return TransferResult(
        request_id=request.request_id, transfer_id=transfer_id,
        source_node_id=request.source_node_id, destination_node_id=request.destination_node_id,
        transfer_state=TRANSFER_COMPLETED, integrity_verified=True, error_detail=None,
        correlation_id=request.correlation_id,
    )


# ---------------------------------------------------------------------------
# remote capability invocation
# ---------------------------------------------------------------------------

CAP_COMPLETED = "COMPLETED"
CAP_UNSUPPORTED = "UNSUPPORTED"
CAP_UNAUTHORIZED = "UNAUTHORIZED"
CAP_FAILED = "FAILED"
CAP_INCOMPLETE = "INCOMPLETE"
CAP_DUPLICATE_CONFLICT = "DUPLICATE_ARTIFACT_CONFLICT"
_CAP_STATES = (CAP_COMPLETED, CAP_UNSUPPORTED, CAP_UNAUTHORIZED, CAP_FAILED, CAP_INCOMPLETE, CAP_DUPLICATE_CONFLICT)

EVIDENCE_STATUS = "NOT_EVIDENCE"
PROMOTION_STATUS = "NOT_PROMOTED"


@dataclass(frozen=True)
class RemoteCapabilityRequest:
    request_id: str
    source_node_id: str
    destination_node_id: str
    artifact_id: str
    capability_id: str
    authority_context: AuthorityContext
    correlation_id: str
    causation_id: str  # the TransferResult.transfer_id that delivered this artifact
    timeout_seconds: float
    requested_at: str = field(default_factory=_now)


@dataclass(frozen=True)
class RemoteCapabilityResult:
    request_id: str
    capability_id: str
    status: str
    structured_result: Any
    error_detail: Optional[str]
    source_node_id: str
    destination_node_id: str
    correlation_id: str
    causation_id: str  # = the RemoteCapabilityRequest.request_id this answers
    produced_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.status not in _CAP_STATES:
            raise FabricError(f"status {self.status!r} is not one of {_CAP_STATES}")
        if self.status == CAP_COMPLETED and self.structured_result is None:
            raise FabricError("status COMPLETED requires a non-None structured_result")

    @property
    def evidence_status(self) -> str:
        return EVIDENCE_STATUS

    @property
    def promotion_status(self) -> str:
        return PROMOTION_STATUS

    @property
    def possession_status(self) -> str:
        return POSSESSION_STATUS


class FabricCapabilityProvider(Protocol):
    """The contract every capability adapter reachable over the fabric
    implements. fabric/capabilities.py's ContentReadCapability is one
    such adapter, built on content_readers -- not a new parser."""

    capability_id: str

    def invoke(self, manifest_dict: dict, payload: bytes) -> tuple:
        """Return (status, structured_result, error_detail). Must not
        raise for an expected failure."""
        ...


CAPABILITIES: dict = {}


def register_capability(provider: FabricCapabilityProvider) -> None:
    CAPABILITIES[provider.capability_id] = provider


class _EnvelopeBytesAcquisitionProvider:
    """Internal AcquisitionProvider wrapping an already-received
    ArtifactEnvelope's payload -- artifact_handoff.handoff() acquires
    this from memory, never re-fetches it from any external source."""

    provider_id = "fabric_envelope"

    def __init__(self, env: ArtifactEnvelope):
        self._env = env

    def acquire(self, reference):
        return ah_interface.AcquisitionOutcome(
            state=ah_interface.ACQUISITION_ACQUIRED,
            data=bytes(self._env.payload),
            filename=None,
            declared_content_type=self._env.declared_content_type,
            error_detail=None,
            evidence=f"received via fabric envelope {self._env.envelope_id}",
        )


class FabricArtifactIndex:
    """Cross-node artifact-identity dedup index: has this artifact_id
    already been seen with a DIFFERENT sha256? In-memory only in this
    bounded mission -- a durable version would reuse envelope.py's
    _FileLock/_atomic_write_bytes exactly as lineage_store.py already
    does, deferred as a documented limitation, not a missing capability
    class."""

    def __init__(self):
        self._seen: dict = {}

    def check_and_record(self, artifact_id: str, sha256: str) -> Optional[str]:
        prior = self._seen.get(artifact_id)
        if prior is not None and prior != sha256:
            return (
                f"artifact_id {artifact_id!r} was previously seen with sha256={prior}, "
                f"now resubmitted with a different sha256={sha256}"
            )
        self._seen[artifact_id] = sha256
        return None


def compute_receipt_id(
    correlation_id: str, causation_id: str, source_node_id: str, destination_node_id: str,
    artifact_id: str, sha256: str, capability_id: str, transfer_state: str, capability_status: str,
) -> str:
    """Deterministic: the same underlying facts always produce the same
    receipt_id, independent of wall-clock time. No random component."""
    canonical = "|".join([
        correlation_id, causation_id, source_node_id, destination_node_id,
        artifact_id, sha256, capability_id, transfer_state, capability_status,
    ])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return envelope.validate_mission_id(f"RCPT-{digest}")


@dataclass(frozen=True)
class FabricReceipt:
    receipt_id: str
    correlation_id: str
    causation_id: str
    source_node_id: str
    destination_node_id: str
    artifact_id: str
    sha256: str
    capability_id: str
    transfer_state: str
    capability_status: str
    generated_at: str = field(default_factory=_now)

    @property
    def trust_status(self) -> str:
        return TRUST_STATUS

    @property
    def truth_status(self) -> str:
        return "RECEIPT_NOT_TRUTH"

    @property
    def evidence_status(self) -> str:
        return EVIDENCE_STATUS

    @property
    def promotion_status(self) -> str:
        return PROMOTION_STATUS

    @property
    def possession_status(self) -> str:
        return POSSESSION_STATUS

    def to_dict(self) -> dict:
        return {
            "receipt_id": self.receipt_id, "correlation_id": self.correlation_id,
            "causation_id": self.causation_id, "source_node_id": self.source_node_id,
            "destination_node_id": self.destination_node_id, "artifact_id": self.artifact_id,
            "sha256": self.sha256, "capability_id": self.capability_id,
            "transfer_state": self.transfer_state, "capability_status": self.capability_status,
            "generated_at": self.generated_at, "trust_status": self.trust_status,
            "truth_status": self.truth_status, "evidence_status": self.evidence_status,
            "promotion_status": self.promotion_status, "possession_status": self.possession_status,
        }


def _result_and_receipt(request: RemoteCapabilityRequest, *, status: str, structured_result: Any,
                         error_detail: Optional[str], sha256: str = "", transfer_state: str = TRANSFER_COMPLETED) -> tuple:
    result = RemoteCapabilityResult(
        request_id=request.request_id, capability_id=request.capability_id, status=status,
        structured_result=structured_result, error_detail=error_detail,
        source_node_id=request.destination_node_id, destination_node_id=request.source_node_id,
        correlation_id=request.correlation_id, causation_id=request.request_id,
    )
    receipt = FabricReceipt(
        receipt_id=compute_receipt_id(
            request.correlation_id, request.request_id, request.destination_node_id, request.source_node_id,
            request.artifact_id, sha256, request.capability_id, transfer_state, status,
        ),
        correlation_id=request.correlation_id, causation_id=request.request_id,
        source_node_id=request.destination_node_id, destination_node_id=request.source_node_id,
        artifact_id=request.artifact_id, sha256=sha256, capability_id=request.capability_id,
        transfer_state=transfer_state, capability_status=status,
    )
    return result, receipt


def process_remote_capability_request(
    request: RemoteCapabilityRequest,
    transport: FabricTransport,
    *,
    lineage_store=None,
    artifact_index: Optional[FabricArtifactIndex] = None,
) -> tuple:
    """PC_NODE (or any destination) side of the fabric: pull the waiting
    envelope, verify its hash again (independent of the check
    submit_transfer already did), preserve provenance through the real
    artifact_handoff pipeline, enforce authority, dispatch to a
    registered capability, and produce a (RemoteCapabilityResult,
    FabricReceipt) pair. Never raises for an expected failure.
    """
    pending = transport.pull(request.destination_node_id)
    matching = [e for e in pending if e.artifact_id == request.artifact_id]
    # Envelopes not matching this request go back so they aren't lost for
    # a concurrent/subsequent request against a different artifact_id.
    for e in pending:
        if e.artifact_id != request.artifact_id:
            transport.deliver(request.destination_node_id, e)

    if not matching:
        return _result_and_receipt(
            request, status=CAP_FAILED, structured_result=None,
            error_detail=f"no envelope for artifact_id {request.artifact_id!r} is waiting at {request.destination_node_id!r}",
        )
    env = matching[0]

    reason = validate_envelope(env)
    if reason is not None:
        return _result_and_receipt(request, status=CAP_FAILED, structured_result=None, error_detail=reason, sha256=env.sha256)

    if artifact_index is not None:
        conflict = artifact_index.check_and_record(env.artifact_id, env.sha256)
        if conflict is not None:
            return _result_and_receipt(
                request, status=CAP_DUPLICATE_CONFLICT, structured_result=None, error_detail=conflict, sha256=env.sha256,
            )

    if not authority_permits(request.authority_context, request.capability_id):
        return _result_and_receipt(
            request, status=CAP_UNAUTHORIZED, structured_result=None,
            error_detail=(
                f"actor {request.authority_context.actor_id!r} is not authorized for capability "
                f"{request.capability_id!r} (granted: {request.authority_context.granted_capability_ids})"
            ),
            sha256=env.sha256,
        )

    provider = CAPABILITIES.get(request.capability_id)
    if provider is None:
        return _result_and_receipt(
            request, status=CAP_UNSUPPORTED, structured_result=None,
            error_detail=f"no capability registered under {request.capability_id!r}", sha256=env.sha256,
        )

    reference = ah_interface.ArtifactReference(
        source_provider="fabric_envelope", source_reference=env.envelope_id,
        declared_filename=None, declared_content_type=env.declared_content_type,
    )
    manifest = ah_interface.handoff(reference, _EnvelopeBytesAcquisitionProvider(env), lineage_store=lineage_store)

    try:
        status, structured_result, error_detail = provider.invoke(manifest.to_dict(), bytes(env.payload))
    except Exception as exc:  # noqa: BLE001 -- converted to an honest FAILED result, never propagated
        return _result_and_receipt(
            request, status=CAP_FAILED, structured_result=None,
            error_detail=f"capability {request.capability_id!r} raised an unexpected exception: {exc!r}",
            sha256=env.sha256,
        )

    if status not in _CAP_STATES:
        return _result_and_receipt(
            request, status=CAP_INCOMPLETE, structured_result=None,
            error_detail=f"capability {request.capability_id!r} returned an invalid status {status!r}",
            sha256=env.sha256,
        )
    if status == CAP_COMPLETED and structured_result is None:
        return _result_and_receipt(
            request, status=CAP_INCOMPLETE, structured_result=None,
            error_detail=f"capability {request.capability_id!r} reported COMPLETED but returned no structured_result",
            sha256=env.sha256,
        )

    return _result_and_receipt(request, status=status, structured_result=structured_result, error_detail=error_detail, sha256=env.sha256)
