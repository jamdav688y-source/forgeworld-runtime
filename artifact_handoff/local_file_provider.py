"""Local-file acquisition adapter: ONE implementation of interface.py's
AcquisitionProvider Protocol, for reading a synthetic fixture already on
local disk. `source_reference` is interpreted as a local filesystem path
and nothing else -- this is deliberately the smallest possible adapter,
used here only to prove the seam end-to-end with local fixtures. A
future Gmail/Drive adapter is a second file implementing the same
Protocol; interface.py does not change.

Does not execute, import, or interpret the file's contents -- acquisition
is I/O only (open + read).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from artifact_handoff import interface  # noqa: E402


class LocalFileAcquisitionProvider:
    provider_id = "local_file"

    def acquire(self, reference: "interface.ArtifactReference") -> "interface.AcquisitionOutcome":
        if reference.source_provider != self.provider_id:
            return interface.AcquisitionOutcome(
                state=interface.ACQUISITION_FAILED,
                data=None,
                filename=reference.declared_filename,
                declared_content_type=reference.declared_content_type,
                error_detail=(
                    f"reference.source_provider {reference.source_provider!r} does not match "
                    f"provider_id {self.provider_id!r}"
                ),
                evidence="provider/reference mismatch",
            )

        path = Path(reference.source_reference)
        if not path.exists():
            return interface.AcquisitionOutcome(
                state=interface.ACQUISITION_UNREACHABLE,
                data=None,
                filename=reference.declared_filename or path.name,
                declared_content_type=reference.declared_content_type,
                error_detail=f"no file at {path}",
                evidence=f"path {path} does not exist",
            )
        if not path.is_file():
            return interface.AcquisitionOutcome(
                state=interface.ACQUISITION_FAILED,
                data=None,
                filename=reference.declared_filename or path.name,
                declared_content_type=reference.declared_content_type,
                error_detail=f"{path} is not a regular file",
                evidence=f"path {path} exists but is not a regular file",
            )

        try:
            data = path.read_bytes()
        except OSError as exc:
            return interface.AcquisitionOutcome(
                state=interface.ACQUISITION_FAILED,
                data=None,
                filename=reference.declared_filename or path.name,
                declared_content_type=reference.declared_content_type,
                error_detail=str(exc),
                evidence=f"read of {path} failed: {exc}",
            )

        return interface.AcquisitionOutcome(
            state=interface.ACQUISITION_ACQUIRED,
            data=data,
            filename=reference.declared_filename or path.name,
            declared_content_type=reference.declared_content_type,
            error_detail=None,
            evidence=f"read {len(data)} bytes from local path {path}",
        )
