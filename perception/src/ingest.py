"""Governed CAPTURE + HASH stage.

This is the *only* way a screenshot enters the Perception Gateway. Per the
mission brief: "Copy them into the repository only through the repository's
governed ingestion mechanism. Do not alter the originals." Concretely:

  * the source file is opened read-only and never written to or moved;
  * the bytes are copied verbatim into content-addressed storage
    (`perception/data/images/<sha256>.<ext>`) -- the sha256 IS the filename,
    so a second ingest of the same bytes is a no-op, not a duplicate;
  * every CAPTURE and HASH transition is appended to the *same*
    `whatsapp/ledgers/execution_ledger.jsonl` used by the WhatsApp
    Intelligence Membrane, via `whatsapp.src.ledger.append` directly --
    no new ledger module, no new file-locking code (see
    perception/governance/00_DISCOVERY_REPORT.md's Event Bus / Execution
    Ledger reuse rows).

`perception/data/` is gitignored (runtime state, like `whatsapp/ledgers/`),
mirroring this repo's existing split between committed fixtures and
uncommitted runtime data.
"""
from pathlib import Path

from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso, sha256_hex
from .imaging import UnsupportedPNGError, decode_png

MODULE_ROOT = Path(__file__).resolve().parent.parent
IMAGE_STORE = MODULE_ROOT / "data" / "images"

_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class IngestError(Exception):
    """Raised when a source file cannot be governed-ingested (fail closed)."""


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def ingest_image(source_path, capture_source: str, device_note: str = "") -> dict:
    """CAPTURE + HASH. Returns a validated VisualObservation.

    `source_path` is read, never written to. Raises IngestError (fail
    closed) if the file is missing, empty, or not decodable as a supported
    PNG -- a VisualObservation is never fabricated for bytes we could not
    actually verify.
    """
    source_path = Path(source_path)
    if not source_path.is_file():
        raise IngestError(f"source file does not exist: {source_path}")

    data = source_path.read_bytes()
    if not data:
        raise IngestError(f"source file is empty: {source_path}")

    digest = sha256_hex(data)
    _record("CAPTURE", image_sha256=digest, source_path=str(source_path), state="RECEIVED")

    ext = source_path.suffix.lower() or ".png"
    mime_type = _MIME_BY_EXT.get(ext, "application/octet-stream")

    IMAGE_STORE.mkdir(parents=True, exist_ok=True)
    stored_path = IMAGE_STORE / f"{digest}{ext}"
    if not stored_path.exists():
        stored_path.write_bytes(data)  # copy into governed storage; source untouched
    _record("HASH", image_sha256=digest, stored_path=str(stored_path), state="STORED")

    try:
        width, height, _channels, _pixels = decode_png(data)
    except UnsupportedPNGError as e:
        _record("HASH", image_sha256=digest, state="DECODE_FAILED", reason=str(e))
        raise IngestError(f"cannot decode {source_path} as a supported PNG: {e}") from e

    image_id = f"IMG-{digest[:16]}"
    observation = schema.new_visual_observation(
        image_id=image_id,
        image_sha256=digest,
        width=width,
        height=height,
        file_size_bytes=len(data),
        mime_type=mime_type,
        capture_source=capture_source,
        device_note=device_note,
    )
    errors = schema.validate_visual_observation(observation)
    if errors:
        raise IngestError(f"ingested VisualObservation failed validation: {errors}")

    _record(
        "HASH", image_sha256=digest, state="OBSERVATION_CREATED",
        observation_id=observation["id"],
    )
    return observation


def stored_image_path(image_sha256: str) -> Path:
    """Locate the governed, content-addressed copy for a given sha256."""
    matches = list(IMAGE_STORE.glob(f"{image_sha256}.*"))
    if not matches:
        raise IngestError(f"no governed copy stored for sha256={image_sha256}")
    return matches[0]
