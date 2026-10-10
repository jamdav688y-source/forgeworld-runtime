"""Archive inventory reader: reuses artifact_handoff's already-computed
child manifests -- it never reopens or re-parses the archive's bytes.
zip_unpack.py is the one place archive-format parsing and safety
defenses live; duplicating that logic here would be exactly the
duplicate-reader anti-pattern this microphase is told to avoid.

If no child manifests were supplied (the caller used handoff() rather
than handoff_tree(), or artifact_handoff rejected/failed to unpack this
archive), this reader honestly reports UNSUPPORTED rather than falling
back to parsing the bytes itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from content_readers import interface  # noqa: E402


class ArchiveInventoryReader:
    reader_id = "archive_inventory_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        if not request.child_manifests:
            return interface.ContentReadResult(
                artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
                content_type="application/zip", status=interface.READ_UNSUPPORTED,
                structured_content=None, text_content=None, metadata={},
                provenance_reference=request.artifact_id, warnings=(),
                errors=(
                    "no archive inventory available: no child manifests were supplied. "
                    "This archive was not unpacked via artifact_handoff.handoff_tree() (or "
                    "artifact_handoff rejected/failed to unpack it) -- archive_reader never "
                    "re-parses archive bytes itself.",
                ),
                truncated=False, source_sha256=request.source_sha256,
            )

        inventory = [
            {
                "artifact_id": m.get("artifact_id"),
                "filename": m.get("filename"),
                "detected_content_type": m.get("detected_content_type"),
                "sha256": m.get("sha256"),
                "size": m.get("size"),
                "parent_artifact_id": m.get("parent_artifact_id"),
            }
            for m in request.child_manifests
        ]
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="application/zip", status=interface.READ_OK,
            structured_content=inventory, text_content=None,
            metadata={
                "member_count": len(inventory),
                "source": "reused artifact_handoff child manifests; archive bytes were not re-parsed",
            },
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=False, source_sha256=request.source_sha256,
        )


interface.register_reader("application/zip", ArchiveInventoryReader())
