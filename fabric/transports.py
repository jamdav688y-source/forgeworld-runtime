"""In-memory fabric transport: ONE implementation of interface.py's
FabricTransport Protocol, proving the contract with no network, no
phone connection, and no external service. A future LAN/SSH/HTTP/
Tailscale/Bluetooth/USB/cloud-relay adapter is a second file
implementing the same Protocol; interface.py does not change.

Supports simulating two distinct failure modes for honest-failure
testing: a node simply not registered (UNREACHABLE, the normal "no such
node" case) and a registered node whose deliveries are configured to
fail (a transport-layer failure distinct from unreachability -- e.g. "the
node exists but this delivery attempt failed").
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface  # noqa: E402


class InMemoryFabricTransport:
    transport_id = "in_memory"

    def __init__(self, registered_nodes: tuple = (), failing_nodes: tuple = ()):
        self._inboxes: dict = {node_id: [] for node_id in registered_nodes}
        self._failing_nodes = set(failing_nodes)

    def register_node(self, node_id: str) -> None:
        self._inboxes.setdefault(node_id, [])

    def deliver(self, destination_node_id: str, env: "interface.ArtifactEnvelope") -> dict:
        if destination_node_id in self._failing_nodes:
            return {"delivered": False, "reason": f"simulated transport failure delivering to {destination_node_id!r}"}
        if destination_node_id not in self._inboxes:
            return {"delivered": False, "reason": f"node {destination_node_id!r} is not reachable via this transport"}
        self._inboxes[destination_node_id].append(env)
        return {"delivered": True, "reason": "delivered"}

    def pull(self, node_id: str) -> list:
        if node_id not in self._inboxes:
            return []
        items = self._inboxes[node_id]
        self._inboxes[node_id] = []
        return items
