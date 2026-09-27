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
import hmac
import json
import os
import secrets
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from evidence_envelope import envelope  # noqa: E402 -- validate_mission_id / InvalidMissionIdError / durability primitives (_FileLock/_atomic_write_bytes/_serialize_ledger/LedgerIntegrityError/_canonical) for RequestReplayGuard and message-integrity HMAC
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
    expires_at: Optional[str] = None  # None means non-expiring; otherwise a _now()-format UTC timestamp, enforced by authority_permits()


# The one and only timestamp format expires_at (and granted_at, and every
# other _now()-produced field in this module) is ever written in. Reusing
# it here -- rather than inventing a second representation -- is what lets
# expiry comparison stay compatible with the existing contract.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _parse_expiry(value: str) -> datetime:
    """Parse an expires_at string using _now()'s sole existing timestamp
    convention. The trailing 'Z' means UTC, so the naive datetime strptime
    produces is made explicitly UTC-aware here rather than left ambiguous.
    Raises ValueError for anything else -- callers must fail closed on
    that, not treat it as "no expiry" or fall back to string comparison."""
    parsed = datetime.strptime(value, _TIMESTAMP_FORMAT)
    return parsed.replace(tzinfo=timezone.utc)


def authority_permits(
    context: AuthorityContext,
    capability_id: str,
    evaluation_time: Optional[datetime] = None,
) -> bool:
    """capability_id must be in the explicit allowlist AND, when
    expires_at is set, evaluation_time must be strictly before it.
    Boundary is fail-closed: evaluation_time >= expires_at is expired, an
    exact match included, not just a later one. A malformed/unparseable
    expires_at also fails closed (denies) rather than being silently
    normalized or compared as a raw string. evaluation_time, if supplied,
    must be an aware (UTC) datetime -- a naive one is a caller error this
    function surfaces rather than silently resolving one way or the other."""
    if capability_id not in context.granted_capability_ids:
        return False
    if context.expires_at is None:
        return True
    try:
        expires_at_dt = _parse_expiry(context.expires_at)
    except ValueError:
        return False
    if evaluation_time is None:
        evaluation_time = datetime.now(timezone.utc)
    elif evaluation_time.tzinfo is None:
        raise FabricError(
            "authority_permits() requires an aware (UTC) evaluation_time; "
            "a naive datetime is a caller error, not an ambiguity this "
            "function will silently resolve"
        )
    return evaluation_time < expires_at_dt


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
CAP_DUPLICATE_CONFLICT = "DUPLICATE_ARTIFACT_CONFLICT"  # same artifact_id, different content -- a content-identity conflict, not a replay
CAP_DUPLICATE_COMPLETED = "DUPLICATE_COMPLETED_REQUEST"  # replay of a request_id whose original disposition was CAP_COMPLETED
CAP_DUPLICATE_DENIED = "DUPLICATE_DENIED_REQUEST"  # replay of a request_id whose original disposition was anything else
_CAP_STATES = (
    CAP_COMPLETED, CAP_UNSUPPORTED, CAP_UNAUTHORIZED, CAP_FAILED, CAP_INCOMPLETE,
    CAP_DUPLICATE_CONFLICT, CAP_DUPLICATE_COMPLETED, CAP_DUPLICATE_DENIED,
)

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
    integrity_tag: Optional[str] = None  # MISSION: FW-MESSAGE-INTEGRITY-CONTRACT-001 -- HMAC-SHA256 over every other field, set by sign_request(); None means unsigned (backward compatible: a receiver with no integrity_key configured never looks at this field)
    integrity_key_id: Optional[str] = None  # MISSION: FW-LOCAL-KEY-PROVISIONING-CONTRACT-001 -- NOT secret, safe to travel on the wire; identifies which LocalKeyStore entry resolve_key() must use to verify integrity_tag. Deliberately NOT itself part of canonical_request_fields()'s signed content -- swapping it without the corresponding secret cannot produce a tag that verifies against the newly-named key (see LocalKeyStore/evidence receipt for the argument).


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


# ---------------------------------------------------------------------------
# message integrity: MISSION FW-MESSAGE-INTEGRITY-CONTRACT-001
#
# MESSAGE INTEGRITY ONLY. Explicitly NOT: peer identity (a valid tag proves
# the signer knew `key`, not who the signer is), transport encryption,
# non-repudiation, or execution authority (a validly-signed, unexpired,
# authorized request can still be UNSUPPORTED/INCOMPLETE/etc. -- integrity
# is a precondition checked before authority, never a substitute for it).
#
# Reuses evidence_envelope.envelope._canonical (already used by that
# module's own _event_key ledger fingerprint) for deterministic
# canonicalization, and stdlib hmac/hashlib -- no new dependency, no
# invented cryptography.
# ---------------------------------------------------------------------------

def _canonical_authority_fields(context: AuthorityContext) -> dict:
    return {
        "actor_id": context.actor_id,
        "granted_capability_ids": list(context.granted_capability_ids),
        "granted_by": context.granted_by,
        "granted_at": context.granted_at,
        "expires_at": context.expires_at,
    }


def canonical_request_fields(request: RemoteCapabilityRequest) -> dict:
    """Every governance-relevant field of `request` EXCEPT integrity_tag
    itself, as a JSON-safe dict -- the sole canonicalization contract this
    mission establishes. Deliberately covers the WHOLE request (not a
    hand-picked subset) so a future new field is bound by default rather
    than silently left outside the tag's protection."""
    return {
        "request_id": request.request_id,
        "source_node_id": request.source_node_id,
        "destination_node_id": request.destination_node_id,
        "artifact_id": request.artifact_id,
        "capability_id": request.capability_id,
        "authority_context": _canonical_authority_fields(request.authority_context),
        "correlation_id": request.correlation_id,
        "causation_id": request.causation_id,
        "timeout_seconds": request.timeout_seconds,
        "requested_at": request.requested_at,
    }


def compute_request_integrity_tag(request: RemoteCapabilityRequest, key: bytes) -> str:
    """HMAC-SHA256 over envelope._canonical(canonical_request_fields(request)),
    keyed by `key`. Deterministic: the same fields under the same key
    always produce the same tag, independent of integrity_tag's own
    current value (which is never part of the canonicalized input)."""
    canonical = envelope._canonical(canonical_request_fields(request)).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def sign_request(request: RemoteCapabilityRequest, key: bytes, key_id: Optional[str] = None) -> RemoteCapabilityRequest:
    """Returns a copy of `request` with integrity_tag (and, when key_id is
    given, integrity_key_id) set. The sender's one and only integrity-
    related step -- everything downstream (wire serialization, transport,
    verification) treats both fields as ordinary data. key_id is NOT
    secret and is safe to include (MISSION:
    FW-LOCAL-KEY-PROVISIONING-CONTRACT-001); key itself never appears in
    the returned object."""
    tag = compute_request_integrity_tag(request, key)
    if key_id is not None:
        return replace(request, integrity_tag=tag, integrity_key_id=key_id)
    return replace(request, integrity_tag=tag)


def verify_request_integrity(request: RemoteCapabilityRequest, key: bytes) -> bool:
    """True only if integrity_tag is present AND matches the independently
    recomputed tag for every OTHER field, compared in constant time
    (hmac.compare_digest, not ==, per this mission's explicit requirement).
    A missing tag is a verification FAILURE here, not a special case --
    callers that want to tolerate unsigned requests do so by not calling
    this function at all (by never configuring an integrity_key), not by
    this function silently accepting None."""
    if request.integrity_tag is None:
        return False
    expected = compute_request_integrity_tag(request, key)
    return hmac.compare_digest(request.integrity_tag, expected)


# ---------------------------------------------------------------------------
# local integrity-key lifecycle: MISSION FW-LOCAL-KEY-PROVISIONING-CONTRACT-001
#
# KEY LIFECYCLE ONLY. Explicitly NOT: peer identity (a key_id names a KEY,
# never a device/actor/human), PKI, certificates, TLS, or a cloud keystore.
# KEY POSSESSION != EXECUTION AUTHORITY: resolve_key() returning secret
# bytes only means integrity verification MAY proceed; authority_permits()
# is a completely separate, unaffected gate downstream.
#
# Metadata reuses evidence_envelope.envelope's exact JSONL/file-lock/
# atomic-write discipline (the same pattern RequestReplayGuard/LineageStore
# already apply -- a fifth application, not a new persistence technology).
# Secret material is stored SEPARATELY from that metadata ledger, one
# plain file per key_id, chmod 0o600 immediately after an atomic write
# (POSIX only, the same platform caveat evidence_envelope._FileLock
# already documents). Secret bytes are never placed in the metadata
# ledger, never logged, never returned by status_of(), and never appear
# in any RemoteCapabilityRequest field (only the resulting integrity_tag
# and the non-secret integrity_key_id do).
# ---------------------------------------------------------------------------

KEY_STATUS_ACTIVE = "ACTIVE"
KEY_STATUS_RETIRED = "RETIRED"
KEY_STATUS_REVOKED = "REVOKED"
_KEY_STATUSES = (KEY_STATUS_ACTIVE, KEY_STATUS_RETIRED, KEY_STATUS_REVOKED)


class KeyProvisioningError(FabricError):
    """Programmer-misuse only (e.g. revoking/superseding an unknown
    key_id) -- never raised for an expected runtime condition (unknown/
    revoked/malformed key_id at VERIFICATION time fails closed via
    resolve_key() returning None, per this module's Failure Law)."""


class LocalKeyStore:
    """Local, file-based lifecycle store for message-integrity keys.

    ROTATION CONTRACT (explicit, not silently decided): rotation is a
    HARD CUTOVER, not a bounded compatibility window. The instant
    provision_key(supersedes=<old_key_id>) returns, the old key is
    durably RETIRED and resolve_key(old_key_id) stops returning its
    secret -- a message signed with it and arriving after rotation fails
    integrity verification, exactly like a REVOKED key would. RETIRED
    and REVOKED are nonetheless independently tracked and independently
    observable via status_of() and the metadata ledger (satisfying
    "revocation must be distinguishable from rotation" at the audit
    layer), even though both currently produce the same fail-closed
    execution outcome. A future microphase could add a bounded grace
    window for RETIRED specifically without touching REVOKED's
    always-immediate semantics.

    STORAGE SECURITY LIMITATION (explicit, not claimed away): this is
    plaintext key material at rest, protected only by POSIX file
    permissions (0o600) on the secret file and the containing
    directory's own permissions -- NOT an OS keychain, NOT a hardware
    security module, NOT encrypted at rest. Anyone with read access to
    this process's filesystem as the same user (or root) can read the
    secret. This is explicitly a LOCAL PROOF primitive, not production
    key management.
    """

    def __init__(self, root: Path, lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._secrets_dir = self.root / "secrets"
        self._secrets_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._secrets_dir, 0o700)
        except OSError:
            pass  # best-effort on platforms without POSIX permission bits
        self.ledger_path = self.root / "key_metadata.jsonl"
        self.lock_path = self.root / "key_metadata.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    def _read_all(self) -> list:
        if not self.ledger_path.exists():
            return []
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(
                        f"key metadata ledger {self.ledger_path} line {line_number} is not "
                        "newline-terminated (truncated or partially written)"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    raise envelope.LedgerIntegrityError(
                        f"key metadata ledger {self.ledger_path} line {line_number} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(record, dict) or "key_id" not in record or "status" not in record:
                    raise envelope.LedgerIntegrityError(
                        f"key metadata ledger {self.ledger_path} line {line_number} is missing "
                        "required field 'key_id' or 'status'"
                    )
                if record["status"] not in _KEY_STATUSES:
                    raise envelope.LedgerIntegrityError(
                        f"key metadata ledger {self.ledger_path} line {line_number} has an invalid "
                        f"status {record['status']!r}"
                    )
                records.append(record)
        return records

    def _append(self, record: dict) -> None:
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all()
            envelope._atomic_write_bytes(self.ledger_path, envelope._serialize_ledger(records + [record]))

    def _latest_status(self, key_id: str) -> Optional[str]:
        # Status transitions are APPENDED (never overwritten in place),
        # matching evidence_envelope's own lifecycle-ledger style -- the
        # last matching record wins.
        latest = None
        for r in self._read_all():
            if r["key_id"] == key_id:
                latest = r
        return latest["status"] if latest is not None else None

    def _secret_path(self, key_id: str) -> Path:
        return self._secrets_dir / f"{key_id}.secret"

    def provision_key(self, *, supersedes: Optional[str] = None, key_bytes: Optional[bytes] = None) -> str:
        """Generates a fresh key_id and (unless key_bytes is given, for
        deterministic testing only) fresh cryptographically secure secret
        material via secrets.token_bytes(32) -- never derived from a
        username, device name, timestamp, or password, and no KDF is
        invented. Writes the secret file atomically, chmod 0o600
        immediately after, then appends an ACTIVE metadata record. If
        `supersedes` names a currently-ACTIVE key, this is a ROTATION:
        the old key's RETIRED transition is appended in the SAME call,
        under the same lock, so no caller can observe the old key still
        ACTIVE after this method returns while the new key is also
        ACTIVE. Returns the new key_id; NEVER returns secret bytes."""
        if supersedes is not None:
            with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
                current = self._latest_status(supersedes)
                if current is None:
                    raise KeyProvisioningError(f"cannot supersede unknown key_id {supersedes!r}")
                if current != KEY_STATUS_ACTIVE:
                    raise KeyProvisioningError(
                        f"cannot supersede key_id {supersedes!r}: current status is {current!r}, not {KEY_STATUS_ACTIVE!r}"
                    )
                records = self._read_all()
                key_id = envelope.validate_mission_id(f"IKEY-{uuid.uuid4().hex}")
                secret = key_bytes if key_bytes is not None else secrets.token_bytes(32)
                self._write_secret(key_id, secret)
                new_records = records + [
                    {"key_id": supersedes, "status": KEY_STATUS_RETIRED, "algorithm": "HMAC-SHA256",
                     "created_at": _now(), "supersedes": None, "revoked_at": None, "reason": f"superseded by {key_id}"},
                    {"key_id": key_id, "status": KEY_STATUS_ACTIVE, "algorithm": "HMAC-SHA256",
                     "created_at": _now(), "supersedes": supersedes, "revoked_at": None, "reason": None},
                ]
                envelope._atomic_write_bytes(self.ledger_path, envelope._serialize_ledger(new_records))
                return key_id
        key_id = envelope.validate_mission_id(f"IKEY-{uuid.uuid4().hex}")
        secret = key_bytes if key_bytes is not None else secrets.token_bytes(32)
        self._write_secret(key_id, secret)
        self._append({
            "key_id": key_id, "status": KEY_STATUS_ACTIVE, "algorithm": "HMAC-SHA256",
            "created_at": _now(), "supersedes": None, "revoked_at": None, "reason": None,
        })
        return key_id

    def _write_secret(self, key_id: str, secret: bytes) -> None:
        path = self._secret_path(key_id)
        envelope._atomic_write_bytes(path, secret)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX permission bits

    def revoke_key(self, key_id: str, reason: str = "") -> None:
        """Appends a REVOKED transition record, distinct from RETIRED.
        Idempotent: revoking an already-REVOKED key_id is a no-op.
        Raises KeyProvisioningError for an unknown key_id (a programmer/
        operator error -- revoking a key that was never provisioned is
        never an expected runtime condition for a caller that already
        has a key_id to revoke)."""
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            current = self._latest_status(key_id)
            if current is None:
                raise KeyProvisioningError(f"cannot revoke unknown key_id {key_id!r}")
            if current == KEY_STATUS_REVOKED:
                return
            records = self._read_all()
            envelope._atomic_write_bytes(self.ledger_path, envelope._serialize_ledger(records + [
                {"key_id": key_id, "status": KEY_STATUS_REVOKED, "algorithm": "HMAC-SHA256",
                 "created_at": _now(), "supersedes": None, "revoked_at": _now(), "reason": reason},
            ]))

    def status_of(self, key_id: str) -> Optional[str]:
        """Current lifecycle status of key_id, or None if never
        provisioned in this store. Never returns secret material. A
        malformed key_id (fails validate_mission_id's format contract)
        also returns None rather than raising -- fail closed uniformly,
        matching resolve_key()'s own contract."""
        try:
            key_id = envelope.validate_mission_id(key_id)
        except envelope.InvalidMissionIdError:
            return None
        return self._latest_status(key_id)

    def resolve_key(self, key_id: str) -> Optional[bytes]:
        """Returns secret bytes for key_id IF AND ONLY IF its current
        status is ACTIVE. Returns None uniformly for an unknown,
        malformed, RETIRED, or REVOKED key_id -- callers (this module's
        process_remote_capability_request()) fail closed on None without
        needing to distinguish why, exactly like
        verify_request_integrity() already fails closed uniformly on a
        missing/malformed/mismatched tag."""
        try:
            key_id = envelope.validate_mission_id(key_id)
        except envelope.InvalidMissionIdError:
            return None
        if self._latest_status(key_id) != KEY_STATUS_ACTIVE:
            return None
        path = self._secret_path(key_id)
        if not path.exists():
            return None
        return path.read_bytes()

    def active_key_for_signing(self) -> Optional[tuple]:
        """Convenience for a sender: returns (key_id, secret_bytes) for
        the single most-recently-provisioned ACTIVE key in this store,
        or None if no key is ACTIVE. Not used by verification at all --
        a sender-side helper only, so a test/future client script does
        not need to track key_id bookkeeping itself."""
        latest_active_id = None
        for r in self._read_all():
            if r["status"] == KEY_STATUS_ACTIVE:
                latest_active_id = r["key_id"]
            elif r["key_id"] == latest_active_id:
                latest_active_id = None  # a later non-ACTIVE record for the same key_id supersedes it
        if latest_active_id is None:
            return None
        secret = self.resolve_key(latest_active_id)
        if secret is None:
            return None
        return latest_active_id, secret


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


class RequestReplayConflictError(FabricError):
    """request_id already holds a durably recorded disposition with
    DIFFERENT content -- either a bug or a hostile request_id reuse.
    Never propagates out of process_remote_capability_request(); the
    caller there converts this into an honest CAP_FAILED result, per the
    module's own Failure Law."""


class RequestReplayGuard:
    """Durable at-most-once execution gate, keyed by
    RemoteCapabilityRequest.request_id -- MISSION:
    FW-MESSAGE-IDENTITY-REPLAY-CONTRACT-001. Mirrors
    artifact_handoff.lineage_store.LineageStore's own JSONL/file-lock/
    atomic-write discipline exactly (a fourth application of
    evidence_envelope.envelope's durability primitives, not a new
    persistence technology): identical re-recording of an already-seen
    request_id is an idempotent no-op, recording DIFFERENT content under
    an already-used request_id raises RequestReplayConflictError.

    Records a disposition ONLY for a request that has been evaluated
    against authority (CAP_UNAUTHORIZED, CAP_UNSUPPORTED, CAP_FAILED,
    CAP_INCOMPLETE, or a provider's real status such as CAP_COMPLETED).
    A request that never reached that point (no envelope yet delivered,
    an artifact hash mismatch, an artifact-identity conflict) is treated
    as not-yet-resolved and remains retriable -- those reflect transient
    delivery/data-availability state, not a rendered capability decision,
    and permanently freezing them would defeat legitimate retry of a
    genuinely not-yet-serviceable request."""

    def __init__(self, root: Path, lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "request_dispositions.jsonl"
        self.lock_path = self.root / "request_dispositions.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    def _read_all(self) -> list:
        if not self.ledger_path.exists():
            return []
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(
                        f"request disposition ledger {self.ledger_path} line {line_number} is not "
                        "newline-terminated (truncated or partially written)"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError as exc:
                    raise envelope.LedgerIntegrityError(
                        f"request disposition ledger {self.ledger_path} line {line_number} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(record, dict) or "request_id" not in record:
                    raise envelope.LedgerIntegrityError(
                        f"request disposition ledger {self.ledger_path} line {line_number} is missing "
                        "required field 'request_id'"
                    )
                records.append(record)
        return records

    def get(self, request_id: str) -> Optional[dict]:
        request_id = envelope.validate_mission_id(request_id)
        return next((r for r in self._read_all() if r["request_id"] == request_id), None)

    def record_once(self, disposition: dict) -> dict:
        request_id = envelope.validate_mission_id(disposition["request_id"])
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all()
            existing = next((r for r in records if r["request_id"] == request_id), None)
            if existing is not None:
                if existing == disposition:
                    return existing
                raise RequestReplayConflictError(
                    f"request_id {request_id!r} already recorded with a different disposition"
                )
            envelope._atomic_write_bytes(
                self.ledger_path, envelope._serialize_ledger(records + [disposition])
            )
            return disposition


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
    replay_guard: Optional[RequestReplayGuard] = None,
    integrity_key: Optional[bytes] = None,
    key_store: Optional[LocalKeyStore] = None,
) -> tuple:
    """PC_NODE (or any destination) side of the fabric: pull the waiting
    envelope, verify its hash again (independent of the check
    submit_transfer already did), preserve provenance through the real
    artifact_handoff pipeline, enforce authority, dispatch to a
    registered capability, and produce a (RemoteCapabilityResult,
    FabricReceipt) pair. Never raises for an expected failure.

    key_store (optional, MISSION: FW-LOCAL-KEY-PROVISIONING-CONTRACT-001):
    when supplied, TAKES PRECEDENCE over integrity_key. request.integrity_key_id
    is resolved through key_store.resolve_key() -- which itself fails
    closed (returns None) for an unknown, malformed, RETIRED, or REVOKED
    key_id -- and the resolved secret (never logged, never stored, held
    only for the duration of this call) verifies integrity_tag exactly as
    the integrity_key path already does. A missing integrity_key_id, an
    unresolvable key_id, or a mismatched tag all fail closed (CAP_FAILED)
    before replay/envelope/authority evaluation, identically to the
    integrity_key path. Key ACCEPTANCE and execution AUTHORITY remain
    orthogonal: a resolvable, ACTIVE key only permits verification to
    proceed, it never substitutes for authority_permits() downstream.

    integrity_key (optional, MISSION: FW-MESSAGE-INTEGRITY-CONTRACT-001):
    when supplied AND key_store is not, integrity verification is
    MANDATORY and happens FIRST, before replay handling, envelope
    validation, or authority -- a missing, malformed, or mismatched
    integrity_tag fails closed (CAP_FAILED) without ever consulting
    replay_guard, so a resend of a previously-completed request_id whose
    content has since been mutated is rejected as tampered rather than
    answered with the old, no-longer-matching disposition. Omitting both
    key_store and integrity_key (the default) performs NO integrity
    checking at all, byte-for-byte matching this function's pre-existing
    behavior -- the same optional, backward-compatible pattern
    lineage_store/artifact_index/replay_guard already established.

    replay_guard (optional, MISSION: FW-MESSAGE-IDENTITY-REPLAY-CONTRACT-001):
    when supplied, a request_id already carrying a recorded disposition
    short-circuits here, before the envelope is even pulled -- the
    capability is never re-invoked, and the duplicate result is built
    from the ORIGINAL recorded disposition rather than a fresh authority
    re-evaluation (a replay must not gain or lose authority relative to
    its first delivery). Omitting replay_guard preserves this function's
    exact pre-existing behavior (no replay protection), matching the
    optional, backward-compatible pattern lineage_store/artifact_index
    already established.
    """
    if key_store is not None:
        if request.integrity_key_id is None:
            return _result_and_receipt(
                request, status=CAP_FAILED, structured_result=None,
                error_detail=(
                    f"integrity verification failed: request_id {request.request_id!r} carries no "
                    "integrity_key_id, but this receiver requires a key-store-resolved key"
                ),
            )
        resolved_key = key_store.resolve_key(request.integrity_key_id)
        if resolved_key is None:
            return _result_and_receipt(
                request, status=CAP_FAILED, structured_result=None,
                error_detail=(
                    f"integrity verification failed: key_id {request.integrity_key_id!r} is unknown, "
                    "malformed, retired, or revoked -- request rejected before replay/authority evaluation"
                ),
            )
        if not verify_request_integrity(request, resolved_key):
            return _result_and_receipt(
                request, status=CAP_FAILED, structured_result=None,
                error_detail=(
                    f"integrity verification failed: request_id {request.request_id!r} carries a "
                    "malformed or mismatched integrity_tag under the resolved key -- request rejected "
                    "before replay/authority evaluation"
                ),
            )
    elif integrity_key is not None and not verify_request_integrity(request, integrity_key):
        return _result_and_receipt(
            request, status=CAP_FAILED, structured_result=None,
            error_detail=(
                "integrity verification failed: request_id "
                f"{request.request_id!r} carries a missing, malformed, or mismatched integrity_tag "
                "-- request rejected before replay/authority evaluation"
            ),
        )

    if replay_guard is not None:
        prior = replay_guard.get(request.request_id)
        if prior is not None:
            if prior.get("capability_id") != request.capability_id:
                return _result_and_receipt(
                    request, status=CAP_FAILED, structured_result=None,
                    error_detail=(
                        f"request_id {request.request_id!r} was already recorded for a different "
                        f"capability_id {prior.get('capability_id')!r}; refusing to reuse it for {request.capability_id!r}"
                    ),
                )
            duplicate_status = CAP_DUPLICATE_COMPLETED if prior["status"] == CAP_COMPLETED else CAP_DUPLICATE_DENIED
            return _result_and_receipt(
                request, status=duplicate_status, structured_result=prior["structured_result"],
                error_detail=(
                    f"duplicate delivery of request_id {request.request_id!r}; original disposition was "
                    f"{prior['status']!r}" + (f": {prior['error_detail']}" if prior.get("error_detail") else "")
                ),
                sha256=prior.get("sha256", ""),
            )

    def _finalize(status: str, structured_result: Any, error_detail: Optional[str], sha256: str = "") -> tuple:
        result, receipt = _result_and_receipt(
            request, status=status, structured_result=structured_result, error_detail=error_detail, sha256=sha256,
        )
        if replay_guard is not None:
            disposition = {
                "request_id": request.request_id, "capability_id": request.capability_id,
                "status": status, "structured_result": structured_result, "error_detail": error_detail,
                "sha256": sha256,
            }
            try:
                replay_guard.record_once(disposition)
            except RequestReplayConflictError as exc:
                return _result_and_receipt(
                    request, status=CAP_FAILED, structured_result=None, error_detail=str(exc), sha256=sha256,
                )
        return result, receipt

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
        return _finalize(
            status=CAP_UNAUTHORIZED, structured_result=None,
            error_detail=(
                f"actor {request.authority_context.actor_id!r} is not authorized for capability "
                f"{request.capability_id!r} (granted: {request.authority_context.granted_capability_ids})"
            ),
            sha256=env.sha256,
        )

    provider = CAPABILITIES.get(request.capability_id)
    if provider is None:
        return _finalize(
            status=CAP_UNSUPPORTED, structured_result=None,
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
        return _finalize(
            status=CAP_FAILED, structured_result=None,
            error_detail=f"capability {request.capability_id!r} raised an unexpected exception: {exc!r}",
            sha256=env.sha256,
        )

    if status not in _CAP_STATES:
        return _finalize(
            status=CAP_INCOMPLETE, structured_result=None,
            error_detail=f"capability {request.capability_id!r} returned an invalid status {status!r}",
            sha256=env.sha256,
        )
    if status == CAP_COMPLETED and structured_result is None:
        return _finalize(
            status=CAP_INCOMPLETE, structured_result=None,
            error_detail=f"capability {request.capability_id!r} reported COMPLETED but returned no structured_result",
            sha256=env.sha256,
        )

    return _finalize(status=status, structured_result=structured_result, error_detail=error_detail, sha256=env.sha256)
