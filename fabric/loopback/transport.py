"""LoopbackClientTransport: ONE real, OS-process-crossing implementation
of fabric.interface.FabricTransport (deliver/pull/transport_id --
unchanged from the contract), plus a small set of adapter-specific
extension methods (send_capability_request/recv_capability_response)
needed to carry a RemoteCapabilityRequest/({RemoteCapabilityResult,
FabricReceipt}) pair across the same wire. Those extension methods are
NOT part of the FabricTransport Protocol and never will be -- a concrete
adapter is always free to expose more than the abstract contract
requires; this is exactly the "transport is an adapter" boundary the
mission draws.

Uses multiprocessing.connection (stdlib): AF_UNIX on POSIX, AF_PIPE
(named pipes) on Windows, chosen automatically by the platform. This
adapter never opens a TCP/UDP socket and never listens beyond the local
machine's own IPC namespace.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from multiprocessing import connection
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface as fi  # noqa: E402
from fabric.loopback import wire  # noqa: E402


def make_loopback_address(name: str) -> tuple:
    """Returns (address, family) appropriate to THIS process's platform.
    Only the POSIX/AF_UNIX branch has been exercised in this sandbox;
    the Windows/AF_PIPE branch follows multiprocessing.connection's own
    documented, but here-unverified, platform behavior."""
    if sys.platform == "win32":
        return rf"\\.\pipe\forgeworld-fabric-{name}-{uuid.uuid4().hex}", "AF_PIPE"
    socket_dir = tempfile.mkdtemp(prefix="forgeworld-fabric-")
    return str(Path(socket_dir) / f"{name}.sock"), "AF_UNIX"


def cleanup_loopback_address(address: str, family: str) -> None:
    """Removes the temp directory make_loopback_address() created for a
    POSIX AF_UNIX socket path. Every caller of make_loopback_address()
    must call this when done -- mkdtemp() does not clean up after
    itself, and closing the Listener/Connection does not remove the
    directory it lived in. No-op on Windows: AF_PIPE leaves no
    filesystem artifact for this adapter to clean up."""
    if family == "AF_UNIX":
        shutil.rmtree(Path(address).parent, ignore_errors=True)


class LoopbackClientTransport:
    """Used by the process INITIATING contact (PHONE_NODE in this
    mission's proof). Connects lazily on first use, never at
    construction time, so "destination process absent" is reported as
    an honest deliver() failure through the EXISTING, unmodified
    submit_transfer() classification logic, rather than an exception at
    construction."""

    transport_id = "loopback_ipc"

    def __init__(self, address: str, family: str, authkey: bytes, connect_timeout: float = 5.0, response_timeout: float = 10.0):
        self._address = address
        self._family = family
        self._authkey = authkey
        self._connect_timeout = connect_timeout
        self._response_timeout = response_timeout
        self._conn: Optional[connection.Connection] = None

    def _ensure_connected(self) -> Optional[str]:
        if self._conn is not None:
            return None
        try:
            self._conn = connection.Client(self._address, family=self._family, authkey=self._authkey)
            return None
        except OSError as exc:
            return f"destination node is not reachable: could not connect to {self._address!r} ({exc})"

    def deliver(self, destination_node_id: str, env) -> dict:
        reason = self._ensure_connected()
        if reason is not None:
            return {"delivered": False, "reason": reason}
        try:
            wire.send_message(
                self._conn, "ARTIFACT_ENVELOPE",
                {"for_node_id": destination_node_id, "envelope": wire.envelope_to_wire(env)},
            )
        except OSError as exc:
            return {"delivered": False, "reason": f"transport error while sending envelope: {exc}"}
        kind, payload, error = wire.recv_message(self._conn, timeout=self._response_timeout)
        if error is not None:
            return {"delivered": False, "reason": error}
        if kind != "ARTIFACT_ENVELOPE_ACK":
            return {"delivered": False, "reason": f"unexpected response kind {kind!r} to envelope delivery"}
        return {"delivered": bool(payload.get("delivered")), "reason": payload.get("reason", "")}

    def pull(self, node_id: str) -> list:
        # PHONE_NODE never receives envelopes in this proof; a real
        # bidirectional adapter would implement this symmetrically.
        return []

    def send_capability_request(self, request) -> Optional[str]:
        reason = self._ensure_connected()
        if reason is not None:
            return reason
        try:
            wire.send_message(self._conn, "CAPABILITY_REQUEST", wire.capability_request_to_wire(request))
            return None
        except OSError as exc:
            return f"transport error while sending capability request: {exc}"

    def recv_capability_response(self, timeout: Optional[float] = None):
        """Returns (result, receipt, error)."""
        if self._conn is None:
            return None, None, "not connected: send_capability_request() must succeed first"
        kind, payload, error = wire.recv_message(self._conn, timeout=timeout or self._response_timeout)
        if error is not None:
            return None, None, error
        if kind != "CAPABILITY_RESPONSE":
            return None, None, f"unexpected response kind {kind!r} to capability request"
        return wire.safe_capability_response_from_wire(payload)

    def send_shutdown(self) -> None:
        reason = self._ensure_connected()
        if reason is None:
            try:
                wire.send_message(self._conn, "SHUTDOWN", {})
            except OSError:
                pass  # best-effort; the server process may already be gone

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None

    # -- raw escape hatches used ONLY by tests proving malformed/truncated
    # message handling: deliberately bypass wire.send_message()'s normal
    # framing to inject bad bytes onto an already-open connection.
    def _raw_connection_for_testing(self):
        self._ensure_connected()
        return self._conn


def verify_capability_response(request, result, receipt) -> Optional[str]:
    """PHONE_NODE-side verification of whatever came back over the wire:
    identity/correlation/causation consistency, plus an independent
    recomputation of the deterministic receipt_id -- this is transport
    != trust made concrete: a structurally valid response is not
    accepted merely because it parsed, it must actually match what was
    asked and hash to what it claims."""
    if result.request_id != request.request_id:
        return f"result.request_id {result.request_id!r} does not match request.request_id {request.request_id!r}"
    if result.correlation_id != request.correlation_id:
        return f"result.correlation_id mismatch: {result.correlation_id!r} != {request.correlation_id!r}"
    if result.causation_id != request.request_id:
        return f"result.causation_id {result.causation_id!r} does not point back to request.request_id {request.request_id!r}"
    if receipt.correlation_id != request.correlation_id:
        return f"receipt.correlation_id mismatch: {receipt.correlation_id!r} != {request.correlation_id!r}"
    if receipt.causation_id != request.request_id:
        return f"receipt.causation_id {receipt.causation_id!r} does not point back to request.request_id {request.request_id!r}"
    if receipt.artifact_id != request.artifact_id:
        return f"receipt.artifact_id {receipt.artifact_id!r} does not match request.artifact_id {request.artifact_id!r}"
    expected_receipt_id = fi.compute_receipt_id(
        receipt.correlation_id, receipt.causation_id, receipt.source_node_id, receipt.destination_node_id,
        receipt.artifact_id, receipt.sha256, receipt.capability_id, receipt.transfer_state, receipt.capability_status,
    )
    if receipt.receipt_id != expected_receipt_id:
        return "receipt_id does not match independently recomputed value (receipt tampered or corrupted in transit)"
    return None
