"""Authenticated, encrypted, interruption-tolerant store-and-forward sync (Stage E).

Full specification: docs/omega/SYNC_PROTOCOL.md. Summary:

HANDSHAKE (plaintext frames, then everything encrypted)
  I -> R  HELLO     {device_id_I, eph_I (X25519), nonce_I (32 random bytes)}
  R       refuses unknown / revoked devices and any nonce seen before (replay)
  R -> I  HELLO_ACK {device_id_R, eph_R, nonce_R, sig_R = Ed25519_R("R|" + T)}
  I       refuses unknown / revoked / unexpected R, bad signature, seen nonce
  I -> R  AUTH      {sig_I = Ed25519_I("I|" + T)}
  T = sha256 transcript over both hellos. Keys: HKDF-SHA256(X25519(eph_I, eph_R),
  salt = nonce_I || nonce_R, info = "fw-omega-sync-v1|" + T) -> k_I->R, k_R->I.
  Frames: ChaCha20-Poly1305, 96-bit counter nonce that must increase by
  exactly one (a replayed, dropped or reordered frame ends the session).
  Ephemeral keys give forward secrecy; signatures bind both identities.

SESSION
  both: VECTOR {per-device max seq, withheld ids}
  I pushes BATCHes of events R lacks (sender's local order = causal order),
  R imports each event in its own transaction and ACKs; then R pushes to I.
  Payloads above the peer's clearance are WITHHELD (header only). Events are
  verified (id, signature, chain, parents) and imported idempotently; a gap,
  an equivocation or a bad signature never corrupts the store.
  Interruption at any frame leaves every already-imported event committed;
  the next session recomputes vectors and resumes where it stopped.
  Completion triggers reconciliation (conflict detection) and receipts. It
  NEVER runs tasks.

OFFLINE BUNDLES (no simultaneous connectivity)
  export_bundle seals the events a peer lacks to the peer's static X25519 key
  (fresh ephemeral key per bundle), signs the header, writes one file. The
  recipient verifies, refuses replays (bundle nonce) and imports idempotently.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import secrets
import socket
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from omega import receipts, reconcile
from omega.canonical import canonical, digest, loads, sha256_hex
from omega.identity import HAVE_CRYPTO, IdentityUnavailable, b64d, b64e, verify

if HAVE_CRYPTO:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import serialization

PROTOCOL = "fw-omega-sync-v1"
MAX_FRAME = 16 * 1024 * 1024
BATCH = 100


class SyncError(RuntimeError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code


# --------------------------------------------------------------------------
# channels
# --------------------------------------------------------------------------
class SocketChannel:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def send(self, data: bytes):
        self.sock.sendall(struct.pack(">I", len(data)) + data)

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed the connection")
            buf += chunk
        return buf

    def recv(self) -> bytes:
        (n,) = struct.unpack(">I", self._exact(4))
        if n > MAX_FRAME:
            raise SyncError("FRAME_TOO_LARGE", str(n))
        return self._exact(n)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class PipeChannel:
    """In-process duplex channel (tests, same-machine transfer)."""

    def __init__(self, inbox, outbox, timeout=30):
        self.inbox, self.outbox, self.timeout = inbox, outbox, timeout

    @staticmethod
    def pair():
        a, b = queue.Queue(), queue.Queue()
        return PipeChannel(a, b), PipeChannel(b, a)

    def send(self, data: bytes):
        self.outbox.put(bytes(data))

    def recv(self) -> bytes:
        try:
            d = self.inbox.get(timeout=self.timeout)
        except queue.Empty:
            raise ConnectionError("timeout")
        if d is None:
            raise ConnectionError("peer closed the channel")
        return d

    def close(self):
        self.outbox.put(None)


class FaultyChannel:
    """Wraps a channel and drops the connection after `fail_after` frames
    have been sent (interruption tests)."""

    def __init__(self, inner, fail_after: int):
        self.inner, self.left = inner, fail_after

    def send(self, data):
        if self.left <= 0:
            self.inner.close()
            raise ConnectionError("injected interruption")
        self.left -= 1
        self.inner.send(data)

    def recv(self):
        return self.inner.recv()

    def close(self):
        self.inner.close()


class SecureChannel:
    def __init__(self, raw, k_send: bytes, k_recv: bytes, label_send: bytes, label_recv: bytes):
        self.raw = raw
        self.tx, self.rx = ChaCha20Poly1305(k_send), ChaCha20Poly1305(k_recv)
        self.ls, self.lr = label_send, label_recv
        self.n_send = self.n_recv = 0

    def send(self, obj: dict):
        nonce = self.n_send.to_bytes(12, "big")
        self.n_send += 1
        self.raw.send(nonce + self.tx.encrypt(nonce, canonical(obj), self.ls))

    def recv(self) -> dict:
        frame = self.raw.recv()
        nonce, ct = frame[:12], frame[12:]
        if int.from_bytes(nonce, "big") != self.n_recv:
            raise SyncError("FRAME_REPLAYED_OR_REORDERED", f"expected counter {self.n_recv}")
        try:
            pt = self.rx.decrypt(nonce, ct, self.lr)
        except Exception:
            raise SyncError("FRAME_AUTHENTICATION_FAILED")
        self.n_recv += 1
        return loads(pt)

    def close(self):
        self.raw.close()


# --------------------------------------------------------------------------
# handshake
# --------------------------------------------------------------------------
def _eph():
    k = X25519PrivateKey.generate()
    return k, k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _keys(eph_priv, peer_eph: bytes, nonce_i: str, nonce_r: str, transcript: str):
    shared = eph_priv.exchange(X25519PublicKey.from_public_bytes(peer_eph))
    okm = HKDF(algorithm=hashes.SHA256(), length=64, salt=bytes.fromhex(nonce_i + nonce_r),
               info=f"{PROTOCOL}|{transcript}".encode()).derive(shared)
    return okm[:32], okm[32:]


def _check_peer(node, device_id) -> dict:
    peer = node.peer(device_id)
    if peer is None:
        raise SyncError("PEER_UNKNOWN", device_id)
    if peer["revoked"]:
        raise SyncError("PEER_REVOKED", device_id)
    return peer


def _send_plain(ch, obj):
    ch.send(canonical(obj))


def _recv_plain(ch):
    d = loads(ch.recv())
    if d.get("t") == "REFUSED":
        raise SyncError("REFUSED_BY_PEER", d.get("code", ""))
    return d


def handshake_initiator(node, ch, expect: Optional[str] = None, _nonce: Optional[str] = None):
    if not HAVE_CRYPTO:
        raise IdentityUnavailable("sync requires the 'cryptography' package")
    eph, eph_pub = _eph()
    hello = {"t": "HELLO", "v": PROTOCOL, "device_id": node.device_id, "eph": b64e(eph_pub),
             "nonce": _nonce or secrets.token_hex(32), "to": expect}
    _send_plain(ch, hello)
    ack = _recv_plain(ch)
    if ack.get("t") != "HELLO_ACK":
        raise SyncError("PROTOCOL_VIOLATION", "expected HELLO_ACK")
    peer = _check_peer(node, ack["device_id"])
    if expect and ack["device_id"] != expect:
        raise SyncError("UNEXPECTED_PEER", ack["device_id"])
    transcript = digest("sync-transcript", [hello, {k: ack[k] for k in ("device_id", "eph", "nonce")}])
    if not verify(peer["sign_pub"], ack["sig"], f"R|{transcript}".encode()):
        raise SyncError("PEER_AUTHENTICATION_FAILED", ack["device_id"])
    if not node.remember_nonce(ack["nonce"], ack["device_id"], "sync-responder"):
        raise SyncError("REPLAY_DETECTED", "responder nonce reused")
    _send_plain(ch, {"t": "AUTH", "sig": node.identity.sign(f"I|{transcript}".encode())})
    k_ir, k_ri = _keys(eph, b64d(ack["eph"]), hello["nonce"], ack["nonce"], transcript)
    sc = SecureChannel(ch, k_ir, k_ri, b"I->R", b"R->I")
    if sc.recv().get("t") != "READY":
        raise SyncError("PROTOCOL_VIOLATION", "expected READY")
    return sc, peer


def handshake_responder(node, ch):
    if not HAVE_CRYPTO:
        raise IdentityUnavailable("sync requires the 'cryptography' package")
    hello = _recv_plain(ch)
    try:
        if hello.get("t") != "HELLO" or hello.get("v") != PROTOCOL:
            raise SyncError("PROTOCOL_VIOLATION", "expected HELLO")
        if hello.get("to") not in (None, node.device_id):
            raise SyncError("WRONG_RECIPIENT", str(hello.get("to")))
        peer = _check_peer(node, hello["device_id"])
        if not node.remember_nonce(hello["nonce"], hello["device_id"], "sync-initiator"):
            raise SyncError("REPLAY_DETECTED", "initiator nonce reused")
    except SyncError as exc:
        _send_plain(ch, {"t": "REFUSED", "code": exc.code})
        receipts.issue_standalone(node, "SYNC_REFUSED", [], {"code": exc.code, "peer": str(hello.get("device_id"))})
        raise
    eph, eph_pub = _eph()
    mine = {"device_id": node.device_id, "eph": b64e(eph_pub), "nonce": secrets.token_hex(32)}
    transcript = digest("sync-transcript", [hello, mine])
    _send_plain(ch, {"t": "HELLO_ACK", **mine, "sig": node.identity.sign(f"R|{transcript}".encode())})
    auth = _recv_plain(ch)
    if auth.get("t") != "AUTH" or not verify(peer["sign_pub"], auth.get("sig", ""), f"I|{transcript}".encode()):
        _send_plain(ch, {"t": "REFUSED", "code": "PEER_AUTHENTICATION_FAILED"})
        raise SyncError("PEER_AUTHENTICATION_FAILED", hello["device_id"])
    k_ir, k_ri = _keys(eph, b64d(hello["eph"]), hello["nonce"], mine["nonce"], transcript)
    sc = SecureChannel(ch, k_ri, k_ir, b"R->I", b"I->R")
    sc.send({"t": "READY"})
    return sc, peer


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------
@dataclass
class SyncReport:
    peer: str
    role: str
    sent: int = 0
    imported: list = field(default_factory=list)
    backfilled: list = field(default_factory=list)
    duplicates: int = 0
    problems: list = field(default_factory=list)
    complete: bool = False
    conflicts: list = field(default_factory=list)


def _artifacts_for(node, envs) -> dict:
    out = {}
    for env in envs:
        if env["payload"] is None:
            continue
        for sha in env["header"]["artifacts"]:
            data = node.artifact(sha)
            if data is not None and sha not in out:
                mt = node.conn.execute("SELECT media_type FROM artifacts WHERE sha256=?", (sha,)).fetchone()[0]
                out[sha] = {"media_type": mt, "data": b64e(data)}
    return out


def _import_batch(node, msg, peer_id, report: SyncReport):
    for sha, a in msg.get("artifacts", {}).items():
        if not node.import_artifact(sha, b64d(a["data"]), a["media_type"]):
            report.problems.append(("ARTIFACT_HASH_MISMATCH", sha))
    for env in msg["events"]:
        r = node.import_event(env, from_peer=peer_id)
        if r.code == "IMPORTED":
            report.imported.append(r.event_id)
        elif r.code == "BACKFILLED":
            report.backfilled.append(r.event_id)
        elif r.code == "DUPLICATE":
            report.duplicates += 1
        else:
            report.problems.append((r.code, r.event_id, r.reason))


def _push(node, sc, peer, peer_vector, peer_withheld, report):
    sent_vector = dict(peer_vector)
    backfill = node.withheld_backfill_for_peer(peer_withheld, peer["max_privacy"])
    if backfill:
        sc.send({"t": "BATCH", "events": backfill, "artifacts": _artifacts_for(node, backfill)})
        report.sent += len(backfill)
        if sc.recv().get("t") != "ACK":
            raise SyncError("PROTOCOL_VIOLATION", "expected ACK")
    while True:
        envs = node.events_for_peer(sent_vector, peer["max_privacy"], limit=BATCH)
        if not envs:
            break
        sc.send({"t": "BATCH", "events": envs, "artifacts": _artifacts_for(node, envs)})
        report.sent += len(envs)
        ack = sc.recv()
        if ack.get("t") != "ACK":
            raise SyncError("PROTOCOL_VIOLATION", "expected ACK")
        new_vector = ack["vector"]
        if not any(new_vector.get(d, 0) > sent_vector.get(d, 0) for d in new_vector):
            # peer made no progress (e.g. it refused an event): stop, do not loop
            report.problems.append(("PEER_MADE_NO_PROGRESS", ack.get("problems", [])))
            break
        sent_vector = new_vector
    sc.send({"t": "END"})
    node.set_peer_vector(peer["device_id"], sent_vector)


def _receive(node, sc, peer, report):
    while True:
        msg = sc.recv()
        if msg.get("t") == "END":
            return
        if msg.get("t") != "BATCH":
            raise SyncError("PROTOCOL_VIOLATION", "expected BATCH or END")
        before = len(report.problems)
        _import_batch(node, msg, peer["device_id"], report)
        sc.send({"t": "ACK", "vector": node.vector(), "problems": [list(map(str, p)) for p in report.problems[before:]]})


def run_session(node, sc, peer, role: str) -> SyncReport:
    report = SyncReport(peer=peer["device_id"], role=role)
    before = node.state_digest()
    try:
        sc.send({"t": "VECTOR", "vector": node.vector(), "withheld": node.withheld_ids()})
        theirs = sc.recv()
        if theirs.get("t") != "VECTOR":
            raise SyncError("PROTOCOL_VIOLATION", "expected VECTOR")
        if role == "initiator":
            _push(node, sc, peer, theirs["vector"], theirs["withheld"], report)
            _receive(node, sc, peer, report)
        else:
            _receive(node, sc, peer, report)
            _push(node, sc, peer, theirs["vector"], theirs["withheld"], report)
        report.complete = True
    except (ConnectionError, OSError, SyncError) as exc:
        report.problems.append(("INTERRUPTED", type(exc).__name__, str(exc)))
    finally:
        view = reconcile.reconcile_all(node)
        report.conflicts = sorted(k for k, v in view.items() if v["status"] == "CONFLICTED")
        with node.tx() as conn:
            receipts.issue(node, conn, "SYNC_SESSION" if report.complete else "SYNC_INTERRUPTED",
                           report.imported + report.backfilled, before, node.state_digest(),
                           {"peer": report.peer, "role": role, "sent": report.sent,
                            "imported": len(report.imported), "backfilled": len(report.backfilled),
                            "duplicates": report.duplicates, "complete": report.complete,
                            "problem_codes": sorted({str(p[0]) for p in report.problems}),
                            "conflicts": report.conflicts})
    return report


def sync_over(node, ch, role: str, expect: Optional[str] = None) -> SyncReport:
    if role == "initiator":
        sc, peer = handshake_initiator(node, ch, expect)
    else:
        sc, peer = handshake_responder(node, ch)
    return run_session(node, sc, peer, role)


# --------------------------------------------------------------------------
# TCP transport
# --------------------------------------------------------------------------
def serve(node, host: str = "127.0.0.1", port: int = 47470, sessions: int = 1, timeout: float = 120,
          ready: Optional[threading.Event] = None, bound: Optional[list] = None) -> list:
    """Accept `sessions` sync sessions, one at a time. Binds loopback unless
    the operator explicitly chooses a LAN address."""
    reports = []
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        srv.settimeout(timeout)
        if bound is not None:
            bound.append(srv.getsockname()[1])
        if ready is not None:
            ready.set()
        for _ in range(sessions):
            conn, _addr = srv.accept()
            conn.settimeout(timeout)
            ch = SocketChannel(conn)
            try:
                reports.append(sync_over(node, ch, "responder"))
            except (SyncError, ConnectionError, OSError) as exc:
                reports.append(exc)
            finally:
                ch.close()
    return reports


def sync_tcp(node, host: str, port: int, expect: Optional[str] = None, timeout: float = 120) -> SyncReport:
    sock = socket.create_connection((host, port), timeout=timeout)
    ch = SocketChannel(sock)
    try:
        return sync_over(node, ch, "initiator", expect)
    finally:
        ch.close()


# --------------------------------------------------------------------------
# offline sealed bundles
# --------------------------------------------------------------------------
def export_bundle(node, peer_id: str, path, since: Optional[dict] = None) -> dict:
    if not HAVE_CRYPTO:
        raise IdentityUnavailable("bundles require the 'cryptography' package")
    peer = _check_peer(node, peer_id)
    since = peer["last_vector"] if since is None else since
    envs = node.events_for_peer(since, peer["max_privacy"], limit=10 ** 9)
    body = canonical({"events": envs, "artifacts": _artifacts_for(node, envs), "vector": node.vector()})
    eph, eph_pub = _eph()
    nonce = secrets.token_hex(32)
    header = {"v": "fw-omega-bundle-v1", "from": node.device_id, "to": peer_id, "nonce": nonce,
              "eph": b64e(eph_pub), "events": len(envs)}
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=bytes.fromhex(nonce),
               info=f"fw-omega-bundle-v1|{node.device_id}|{peer_id}".encode()).derive(
        eph.exchange(X25519PublicKey.from_public_bytes(peer["kx_pub"])))
    ct = ChaCha20Poly1305(key).encrypt(b"\x00" * 12, body, canonical(header))
    header["ct_sha256"] = sha256_hex(ct)
    doc = {"header": header, "sig": node.identity.sign(digest("bundle", header).encode()), "ct": b64e(ct)}
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc))
    os.replace(tmp, path)
    receipts.issue_standalone(node, "BUNDLE_EXPORTED", [],
                              {"to": peer_id, "events": len(envs), "nonce": nonce})
    return {"path": str(path), "events": len(envs), "nonce": nonce}


def import_bundle(node, path) -> SyncReport:
    if not HAVE_CRYPTO:
        raise IdentityUnavailable("bundles require the 'cryptography' package")
    doc = json.loads(Path(path).read_text())
    header = doc["header"]
    if header.get("v") != "fw-omega-bundle-v1" or header.get("to") != node.device_id:
        raise SyncError("WRONG_RECIPIENT", str(header.get("to")))
    peer = _check_peer(node, header["from"])
    if not verify(peer["sign_pub"], doc["sig"], digest("bundle", header).encode()):
        raise SyncError("PEER_AUTHENTICATION_FAILED", "bundle signature invalid")
    ct = b64d(doc["ct"])
    if sha256_hex(ct) != header["ct_sha256"]:
        raise SyncError("INTEGRITY_FAILURE", "ciphertext hash mismatch")
    if not node.remember_nonce(header["nonce"], header["from"], "bundle"):
        receipts.issue_standalone(node, "BUNDLE_REPLAY_REFUSED", [], {"from": header["from"], "nonce": header["nonce"]})
        raise SyncError("REPLAY_DETECTED", "bundle already imported")
    aad_header = {k: v for k, v in header.items() if k != "ct_sha256"}
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=bytes.fromhex(header["nonce"]),
               info=f"fw-omega-bundle-v1|{header['from']}|{node.device_id}".encode()).derive(
        node.identity.kx_shared(b64d(header["eph"])))
    try:
        body = loads(ChaCha20Poly1305(key).decrypt(b"\x00" * 12, ct, canonical(aad_header)))
    except Exception:
        raise SyncError("INTEGRITY_FAILURE", "bundle decryption failed")
    report = SyncReport(peer=header["from"], role="bundle")
    before = node.state_digest()
    _import_batch(node, body, header["from"], report)
    report.complete = not report.problems
    view = reconcile.reconcile_all(node)
    report.conflicts = sorted(k for k, v in view.items() if v["status"] == "CONFLICTED")
    with node.tx() as conn:
        receipts.issue(node, conn, "BUNDLE_IMPORTED", report.imported, before, node.state_digest(),
                       {"from": header["from"], "imported": len(report.imported), "duplicates": report.duplicates,
                        "problem_codes": sorted({str(p[0]) for p in report.problems}),
                        "conflicts": report.conflicts})
    return report
