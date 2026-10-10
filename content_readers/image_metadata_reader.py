"""Image metadata reader: pure binary header parsing (PNG IHDR chunk,
JPEG SOF marker scan). No Pillow/PIL is installed in this environment,
so no image *decoding* is attempted or possible here -- only reading
fixed-offset/marker-delimited header fields already present in the
bytes. Pixel data is never touched, decoded, or transformed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from content_readers import interface  # noqa: E402

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _read_png_dimensions(data: bytes) -> Optional[tuple]:
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _read_jpeg_dimensions(data: bytes) -> Optional[tuple]:
    if not data.startswith(b"\xff\xd8"):
        return None
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in _JPEG_SOF_MARKERS:
            if i + 9 > n:
                return None
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return width, height
        if marker == 0xD9 or seg_len < 2:
            return None
        i += 2 + seg_len
    return None


class ImageMetadataReader:
    reader_id = "image_metadata_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        if request.detected_content_type == "image/png":
            fmt, dims = "png", _read_png_dimensions(request.data)
        elif request.detected_content_type == "image/jpeg":
            fmt, dims = "jpeg", _read_jpeg_dimensions(request.data)
        else:
            return interface.ContentReadResult(
                artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
                content_type=request.detected_content_type, status=interface.READ_UNSUPPORTED,
                structured_content=None, text_content=None, metadata={},
                provenance_reference=request.artifact_id, warnings=(),
                errors=(f"image_metadata_reader does not support {request.detected_content_type!r}",),
                truncated=False, source_sha256=request.source_sha256,
            )

        width, height = dims if dims else (None, None)
        metadata = {
            "format": fmt, "width": width, "height": height,
            "dimensions_parsed": dims is not None,
            "byte_size": len(request.data),
            "note": "header fields only; pixel data never decoded or transformed",
        }
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type=request.detected_content_type, status=interface.READ_OK,
            structured_content=metadata, text_content=None, metadata=metadata,
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=False, source_sha256=request.source_sha256,
        )


_reader = ImageMetadataReader()
interface.register_reader("image/png", _reader)
interface.register_reader("image/jpeg", _reader)
