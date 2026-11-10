"""Operator attestation: an authenticated human behind consequential events.

DEFECT FIXED: before this module, `human:<name>` was only a string. Any
process with shell access (including a model-driven agent) could write
TASK_AUTHORIZED and trigger an external action.

Now each node registers ONE operator key: an Ed25519 key encrypted at rest
with a passphrase (scrypt n=2^15, r=8, p=1 -> ChaCha20-Poly1305). Event types
in policy.ATTESTED_TYPES are accepted only when their payload carries
`_operator = {operator_id, sig}`, a signature by the unlocked operator key
over (event_type, device_id, actor_id, payload without `_operator`). The
actor must be `human:<operator name>`.

What it protects against: an agent or script that can run commands and read
every file on the device, but does not know the passphrase. It cannot
produce an attestation, so it cannot authorize execution, delete, verify a
payment, change retention, pair or revoke. Executors and effect handlers
re-verify the attestation, so writing rows into SQLite directly does not help.

What it does NOT protect against: someone who knows the passphrase, or
malware that captures it as it is typed. The passphrase is never stored.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Optional

from omega.canonical import digest, sha256_hex
from omega.identity import _need_crypto, b64d, b64e, verify

KDF = {"n": 2 ** 15, "r": 8, "p": 1}


class OperatorError(PermissionError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code


def operator_id_for(pub: bytes) -> str:
    return "op_" + sha256_hex(pub)[:24]


def _derive(passphrase: str, salt: bytes, kdf: dict) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(passphrase.encode("utf-8"))


def attestation_message(event_type: str, device_id: str, actor_id: str, payload: dict) -> bytes:
    body = {k: v for k, v in payload.items() if k != "_operator"}
    return digest("operator-attestation", {"event_type": event_type, "device_id": device_id,
                                           "actor_id": actor_id, "payload": body}).encode("ascii")


class OperatorSession:
    """An unlocked operator key. Keep it only as long as the action needs."""

    def __init__(self, name: str, key):
        from cryptography.hazmat.primitives import serialization
        self.name = name
        self._key = key
        self.pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.operator_id = operator_id_for(self.pub)

    @property
    def actor(self) -> str:
        return f"human:{self.name}"

    def attest(self, event_type: str, device_id: str, actor_id: str, payload: dict) -> dict:
        sig = self._key.sign(attestation_message(event_type, device_id, actor_id, payload))
        return {"operator_id": self.operator_id, "sig": b64e(sig)}


def create(directory, name: str, passphrase: str, kdf: Optional[dict] = None) -> OperatorSession:
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise OperatorError("NAME_INVALID", "operator name: letters, digits, - and _ only")
    if len(passphrase) < 10:
        raise OperatorError("PASSPHRASE_TOO_SHORT", "use at least 10 characters")
    path = Path(directory) / "operator.json"
    if path.exists():
        raise OperatorError("OPERATOR_EXISTS", "refusing to overwrite an operator key")
    kdf = kdf or KDF
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    sess = OperatorSession(name, key)
    ct = ChaCha20Poly1305(_derive(passphrase, salt, kdf)).encrypt(nonce, raw, sess.operator_id.encode())
    doc = {"v": 1, "name": name, "operator_id": sess.operator_id, "pub": b64e(sess.pub), "kdf": kdf,
           "salt": b64e(salt), "nonce": b64e(nonce), "ct": b64e(ct)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, path)
    return sess


def load_public(directory) -> Optional[dict]:
    path = Path(directory) / "operator.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    return {"name": d["name"], "operator_id": d["operator_id"], "pub": b64d(d["pub"])}


def unlock(directory, passphrase: str) -> OperatorSession:
    _need_crypto()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    path = Path(directory) / "operator.json"
    if not path.exists():
        raise OperatorError("NO_OPERATOR", "run `omega operator-init` first")
    d = json.loads(path.read_text())
    try:
        raw = ChaCha20Poly1305(_derive(passphrase, b64d(d["salt"]), d["kdf"])).decrypt(
            b64d(d["nonce"]), b64d(d["ct"]), d["operator_id"].encode())
    except Exception:
        raise OperatorError("PASSPHRASE_WRONG", "operator key did not unlock")
    sess = OperatorSession(d["name"], Ed25519PrivateKey.from_private_bytes(raw))
    if sess.operator_id != d["operator_id"]:
        raise OperatorError("OPERATOR_FILE_CORRUPT")
    return sess


def check(pub: Optional[bytes], event_type: str, device_id: str, actor_id: str, payload: Optional[dict]) -> Optional[str]:
    """None if the attestation is valid, else a reason code."""
    if payload is None:
        return "PAYLOAD_ABSENT"
    att = payload.get("_operator")
    if not isinstance(att, dict) or not isinstance(att.get("sig"), str):
        return "ATTESTATION_MISSING"
    if pub is None:
        return "OPERATOR_UNKNOWN"
    if att.get("operator_id") != operator_id_for(pub):
        return "OPERATOR_MISMATCH"
    if not verify(pub, att["sig"], attestation_message(event_type, device_id, actor_id, payload)):
        return "ATTESTATION_INVALID"
    return None
