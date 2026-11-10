"""Authenticated LAN peer discovery (Stage C).

A node announces a signed UDP beacon {device_id, port, nonce}. A listener
accepts a beacon only if the device is a PAIRED, non-revoked peer, the
signature verifies, and the nonce was not seen before (replayed beacons are
dropped). Discovery is only a hint about where to connect: the sync
handshake authenticates both sides again, so a spoofed address can at worst
cause a refused connection.
"""
from __future__ import annotations

import json
import secrets
import socket
import time
from typing import Optional

from omega.canonical import digest
from omega.identity import verify

PORT = 47474


def beacon(node, sync_port: int) -> bytes:
    b = {"t": "FW_OMEGA_BEACON", "device_id": node.device_id, "port": sync_port, "nonce": secrets.token_hex(16)}
    b["sig"] = node.identity.sign(digest("beacon", {k: v for k, v in b.items() if k != "sig"}).encode())
    return json.dumps(b).encode()


def verify_beacon(node, data: bytes, addr) -> Optional[dict]:
    try:
        b = json.loads(data.decode())
        peer = node.peer(b["device_id"])
        if peer is None or peer["revoked"]:
            return None
        if not verify(peer["sign_pub"], b["sig"], digest("beacon", {k: v for k, v in b.items() if k != "sig"}).encode()):
            return None
        if not node.remember_nonce("beacon:" + b["nonce"], b["device_id"], "discovery"):
            return None
        return {"device_id": b["device_id"], "label": peer["label"], "host": addr[0], "port": int(b["port"])}
    except (ValueError, KeyError, TypeError):
        return None


def announce(node, sync_port: int, target: str = "255.255.255.255", port: int = PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(beacon(node, sync_port), (target, port))


def listen(node, timeout: float = 10, port: int = PORT, bind: str = "0.0.0.0") -> list:
    found, deadline = [], time.time() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((bind, port))
        while time.time() < deadline:
            s.settimeout(max(0.05, deadline - time.time()))
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                break
            r = verify_beacon(node, data, addr)
            if r:
                found.append(r)
                break
    return found
