"""Device identity, pairing offers and short authentication strings.

Each node owns two long-term keys, generated locally and never exported:
    signing   Ed25519  -> device_id = "dev_" + sha256(raw public key)[:32]
    kx        X25519   -> used only to seal offline sync bundles to it

Pairing (mutual, human-confirmed, out of band):
    1. each device prints a pairing OFFER (public keys + fresh nonce);
    2. the operator carries each offer to the other device (copy / QR / file);
    3. both devices compute a 6-digit short authentication string (SAS) over
       BOTH offers; the operator confirms the two screens show the same
       digits and types it in. Without the matching SAS, add_peer refuses.
A substituted offer (man in the middle) changes the SAS on one side.

Requires the `cryptography` package (Termux: `pkg install python-cryptography`;
Windows: `pip install cryptography`). It is a hard requirement: every event is
signed, so without it a node fails closed with IdentityUnavailable.
"""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Optional

from omega.canonical import canonical, digest, loads, sha256_hex

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey)
    from cryptography.exceptions import InvalidSignature
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - exercised only without cryptography
    HAVE_CRYPTO = False


class IdentityUnavailable(RuntimeError):
    pass


class PairingError(ValueError):
    pass


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def device_id_for(sign_pub_raw: bytes) -> str:
    return "dev_" + sha256_hex(sign_pub_raw)[:32]


def _need_crypto():
    if not HAVE_CRYPTO:
        raise IdentityUnavailable("the 'cryptography' package is required for signing, pairing and sync")


def _raw_pub(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _raw_priv(key) -> bytes:
    return key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())


def _write_secret(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class DeviceIdentity:
    def __init__(self, sign_key, kx_key):
        self._sign = sign_key
        self._kx = kx_key
        self.sign_pub = _raw_pub(sign_key)
        self.kx_pub = _raw_pub(kx_key)
        self.device_id = device_id_for(self.sign_pub)

    # -- persistence ------------------------------------------------------
    @classmethod
    def create(cls, directory: Path) -> "DeviceIdentity":
        _need_crypto()
        directory = Path(directory)
        if (directory / "sign.key").exists():
            raise IdentityUnavailable(f"identity already exists in {directory}; refusing to overwrite")
        sign, kx = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
        _write_secret(directory / "sign.key", _raw_priv(sign))
        _write_secret(directory / "kx.key", _raw_priv(kx))
        return cls(sign, kx)

    @classmethod
    def load(cls, directory: Path) -> "DeviceIdentity":
        _need_crypto()
        directory = Path(directory)
        sign = Ed25519PrivateKey.from_private_bytes((directory / "sign.key").read_bytes())
        kx = X25519PrivateKey.from_private_bytes((directory / "kx.key").read_bytes())
        return cls(sign, kx)

    # -- operations -------------------------------------------------------
    def sign(self, data: bytes) -> str:
        return b64e(self._sign.sign(data))

    def kx_shared(self, peer_kx_pub: bytes) -> bytes:
        return self._kx.exchange(X25519PublicKey.from_public_bytes(peer_kx_pub))

    def secret_tag(self, domain: str, data: str) -> str:
        """Keyed, device-secret tag (HMAC-SHA256). Used for identifiers that must
        not be recomputable by anyone who only knows the input (e.g. a phone
        number -> contact id)."""
        import hashlib
        import hmac
        k = hashlib.sha256(b"fw-omega-secret-tag|" + domain.encode() + b"|" + _raw_priv(self._sign)).digest()
        return hmac.new(k, data.encode("utf-8"), hashlib.sha256).hexdigest()

    def pairing_offer(self, label: str, operator_pub: Optional[bytes] = None, operator_name: str = "") -> str:
        if operator_pub is None:
            raise PairingError("register an operator (omega operator-init) before pairing")
        offer = {"v": 1, "device_id": self.device_id, "label": label,
                 "sign_pub": b64e(self.sign_pub), "kx_pub": b64e(self.kx_pub),
                 "operator_pub": b64e(operator_pub), "operator_name": operator_name,
                 "nonce": secrets.token_hex(16)}
        return "FWPAIR1:" + b64e(canonical(offer))


def verify(sign_pub_raw: bytes, signature_b64: str, data: bytes) -> bool:
    _need_crypto()
    try:
        Ed25519PublicKey.from_public_bytes(sign_pub_raw).verify(b64d(signature_b64), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def parse_offer(text: str) -> dict:
    text = text.strip()
    if not text.startswith("FWPAIR1:"):
        raise PairingError("not a ForgeWorld pairing offer")
    try:
        offer = loads(b64d(text[len("FWPAIR1:"):]))
    except Exception as exc:
        raise PairingError(f"malformed pairing offer: {exc}") from exc
    for f in ("device_id", "label", "sign_pub", "kx_pub", "nonce", "operator_pub"):
        if not isinstance(offer.get(f), str):
            raise PairingError(f"pairing offer missing {f}")
    if device_id_for(b64d(offer["sign_pub"])) != offer["device_id"]:
        raise PairingError("pairing offer device_id does not match its signing key")
    return offer


def short_auth_string(offer_a: dict, offer_b: dict) -> str:
    """Order-independent 6-digit SAS over both offers."""
    pair = sorted([offer_a, offer_b], key=lambda o: o["device_id"])
    d = digest("pairing-sas", [[o["device_id"], o["sign_pub"], o["kx_pub"], o.get("operator_pub", ""), o["nonce"]]
                               for o in pair])
    return f"{int(d[:12], 16) % 1_000_000:06d}"
