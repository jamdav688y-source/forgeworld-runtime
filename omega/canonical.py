"""Deterministic serialization and domain-separated hashing.

REUSED, not reimplemented: cognition.cxp.canonical_bytes (strict canonical
JSON: sorted keys, compact separators, UTF-8, no floats / NaN / non-JSON
types). Money and scores are therefore always integers (minor units,
per-mille), never floats.

Every identity is sha256 over a domain tag + NUL + canonical bytes, so two
different kinds of object can never share an identifier.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cognition.cxp import canonical_bytes, CXPError  # noqa: E402  (reuse)

DOMAIN_PREFIX = "forgeworld.omega.v1."


class CanonicalError(ValueError):
    pass


def canonical(obj) -> bytes:
    try:
        return canonical_bytes(obj)
    except CXPError as exc:  # re-raise with an omega-local type
        raise CanonicalError(str(exc)) from exc


def digest(domain: str, obj) -> str:
    h = hashlib.sha256()
    h.update((DOMAIN_PREFIX + domain).encode("ascii") + b"\x00")
    h.update(canonical(obj))
    return h.hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def loads(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return json.loads(data)
