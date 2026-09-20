"""Fabric capability adapters: thin wrappers around ALREADY-EXISTING
substrate, registered under fabric.interface.CAPABILITIES. Neither of
these reimplements any parsing/reading logic -- ContentReadCapability
delegates entirely to content_readers (Microphase 02); EchoCapability is
the one deliberately trivial mock, kept only to prove the "MOCK
capability" path the mission allows, distinct from real reuse.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from fabric import interface  # noqa: E402
from content_readers import interface as cr_interface  # noqa: E402
from content_readers import text_readers  # noqa: E402,F401 -- registers text/plain etc.

_STATUS_MAP = {
    cr_interface.READ_OK: interface.CAP_COMPLETED,
    cr_interface.READ_UNSUPPORTED: interface.CAP_UNSUPPORTED,
    cr_interface.READ_MALFORMED: interface.CAP_FAILED,
    cr_interface.READ_FAILED: interface.CAP_FAILED,
}


class ContentReadCapability:
    """Reuses content_readers.read_content() -- an EXISTING, already
    tested capability -- rather than building a second reader here."""

    capability_id = "content_read"

    def invoke(self, manifest_dict: dict, payload: bytes) -> tuple:
        request = cr_interface.build_request_from_manifest(manifest_dict, payload)
        result = cr_interface.read_content(request)
        status = _STATUS_MAP.get(result.status, interface.CAP_FAILED)
        if status == interface.CAP_COMPLETED:
            return status, result.to_dict(), None
        error_detail = "; ".join(result.errors) if result.errors else f"content_readers reported {result.status}"
        return status, None, error_detail


class EchoCapability:
    """Deliberately trivial MOCK capability: reports what it received
    without reading or interpreting it. Kept to prove the fabric
    contract does not require a real reader to be registered for every
    test -- a MOCK is an equally valid FabricCapabilityProvider."""

    capability_id = "echo_mock"

    def invoke(self, manifest_dict: dict, payload: bytes) -> tuple:
        return interface.CAP_COMPLETED, {"echoed_byte_count": len(payload), "artifact_id": manifest_dict.get("artifact_id")}, None


interface.register_capability(ContentReadCapability())
interface.register_capability(EchoCapability())
