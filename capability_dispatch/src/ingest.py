"""Governed ingestion of a FW-CAP-DISPATCH candidate-list packet.

Structurally parallel to perception/src/ingest.py's governed CAPTURE+HASH
stage: the source file is opened read-only and never modified; its bytes
are copied verbatim into content-addressed storage
(capability_dispatch/data/artifacts/<sha256>.json); every stage transition
is appended to the SAME whatsapp/ledgers/execution_ledger.jsonl the rest
of this repository already uses (via whatsapp.src.ledger, imported
directly -- no new ledger module).

Performs the 10 validation steps enumerated in
evidence/FW-CAP-DISPATCH-004/artifact_validation.json:
JSON syntax, required fields, artifact-ID consistency, source-hash format,
candidate-count verification, duplicate-name detection, category
normalization (original preserved, normalized recorded separately),
canonical-hint format review, epistemic-state review (fails closed if a
source packet tries to hand a candidate a stronger-than-floor state), and
a minimal claims-integrity check (every free-text source_notes field is
carried through verbatim, never rewritten into a structured claim).
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso, sha256_hex

MODULE_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_STORE = MODULE_ROOT / "data" / "artifacts"

# Magic-byte signatures, checked before trusting any filename extension --
# TEST-DISPATCH-002's requirement ("a JPEG payload named .png is identified
# from content rather than extension") applies to every file this module
# ever reads, not just JSON packets. PNG_SIGNATURE mirrors
# perception/src/imaging.py's constant (not imported, to keep this module
# import-independent of the perception package for a check this simple).
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


def detect_media_type(data: bytes) -> str:
    """Content-based media-type detection -- never trusts a filename
    extension. Returns a MIME-ish string; 'application/json' only after
    confirming the bytes actually parse as JSON, not merely because a
    caller named the file *.json."""
    if data[:8] == _PNG_SIGNATURE:
        return "image/png"
    if data[:3] == _JPEG_SIGNATURE:
        return "image/jpeg"
    try:
        json.loads(data)
        return "application/json"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "application/octet-stream"


_CATEGORY_NORMALIZATION = {
    "cli-utility": "cli_utility",
    "scripting-utility": "scripting_utility",
    "secret-scanning-cli": "secret_scanning_cli",
    "automation-agent": "automation_agent",
    "unknown": "unknown",
}


class IngestError(Exception):
    """Raised when the packet cannot be governed-ingested (fail closed)."""


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def _normalize_name(observed_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", observed_name.lower()).strip("_")


def _normalize_category(observed_category: str) -> str:
    return _CATEGORY_NORMALIZATION.get(observed_category, observed_category.replace("-", "_"))


def _is_wellformed_url_or_none(value):
    if value is None:
        return True
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme) and bool(parsed.netloc)
    except (ValueError, AttributeError):
        return False


def ingest_candidate_packet(source_path, capture_source: str) -> dict:
    """CAPTURE + HASH + the 10-step validation. Returns
    (SourceObservation, [CapabilityCandidate, ...]). Raises IngestError
    (fail closed) on any validation failure -- nothing partial is ever
    returned."""
    source_path = Path(source_path)
    if not source_path.is_file():
        raise IngestError(f"source artifact does not exist: {source_path}")

    data = source_path.read_bytes()
    if not data:
        raise IngestError(f"source artifact is empty: {source_path}")

    digest = sha256_hex(data)
    _record("CAPTURE", artifact_sha256=digest, source_path=str(source_path), state="RECEIVED")

    # Content-based media-type detection, independent of source_path's
    # extension (TEST-DISPATCH-002: a payload's actual bytes decide its
    # type, not what it was named).
    detected_media_type = detect_media_type(data)
    if detected_media_type != "application/json":
        _record(
            "HASH", artifact_sha256=digest, state="MEDIA_TYPE_MISMATCH",
            filename=source_path.name, detected_media_type=detected_media_type,
        )
        raise IngestError(
            f"{source_path.name!r} was detected as {detected_media_type!r} by content, "
            f"not application/json, regardless of its filename -- refusing to ingest it as a candidate packet"
        )

    # Step 1: JSON syntax validation.
    try:
        packet = json.loads(data)
    except json.JSONDecodeError as e:
        _record("HASH", artifact_sha256=digest, state="JSON_PARSE_FAILED", reason=str(e))
        raise IngestError(f"source artifact is not valid JSON: {e}") from e

    ARTIFACT_STORE.mkdir(parents=True, exist_ok=True)
    stored_path = ARTIFACT_STORE / f"{digest}.json"
    if not stored_path.exists():
        stored_path.write_bytes(data)
    _record("HASH", artifact_sha256=digest, stored_path=str(stored_path), state="STORED")

    # Step 2: required-field validation.
    for field in ("artifact_id", "candidate_count", "candidates"):
        if field not in packet:
            raise IngestError(f"packet missing required field: {field}")

    # Step 3: artifact-ID consistency (declared ID must reference this mission).
    if "FW-CAP-DISPATCH-004" not in packet["artifact_id"]:
        raise IngestError(
            f"artifact_id {packet['artifact_id']!r} does not reference FW-CAP-DISPATCH-004"
        )

    # Step 4: source-hash format -- this ingester computed the hash itself
    # (sha256_hex above uses the same HEX64-compatible hashlib.sha256
    # digest perception.src.common validates against), so this step is
    # satisfied by construction; no separately-declared hash to check
    # against in this packet shape.

    candidates_raw = packet["candidates"]

    # Step 5: candidate-count verification.
    if packet["candidate_count"] != len(candidates_raw):
        raise IngestError(
            f"declared candidate_count={packet['candidate_count']} does not match "
            f"len(candidates)={len(candidates_raw)}"
        )

    # Step 6: duplicate-name detection (case-insensitive).
    seen_names = set()
    for c in candidates_raw:
        key = c.get("observed_name", "").lower()
        if key in seen_names:
            raise IngestError(f"duplicate candidate name (case-insensitive): {c.get('observed_name')!r}")
        seen_names.add(key)

    source_observation = schema.new_source_observation(
        artifact_id=packet["artifact_id"], artifact_sha256=digest, media_type=detected_media_type,
        filename=source_path.name, file_size_bytes=len(data), candidate_count=len(candidates_raw),
        capture_source=capture_source, source_notes=packet.get("note", ""),
    )
    errors = schema.validate_source_observation(source_observation)
    if errors:
        raise IngestError(f"SourceObservation failed validation: {errors}")

    candidates = []
    for raw in candidates_raw:
        if "observed_name" not in raw:
            raise IngestError(f"candidate missing observed_name: {raw!r}")

        # Step 8: canonical-hint format review -- well-formed URL or None,
        # never guessed/repaired.
        hint = raw.get("canonical_hint")
        if not _is_wellformed_url_or_none(hint):
            raise IngestError(
                f"candidate {raw['observed_name']!r} has a malformed canonical_hint "
                f"{hint!r} -- refusing to silently repair it"
            )

        # Step 7: category normalization -- original preserved, normalized
        # recorded separately, method stated.
        observed_category = raw.get("observed_category", "unknown")
        normalized_category = _normalize_category(observed_category)

        candidate = schema.new_capability_candidate(
            artifact_id=packet["artifact_id"], artifact_sha256=digest,
            observed_name=raw["observed_name"], normalized_name=_normalize_name(raw["observed_name"]),
            observed_category=observed_category, normalized_category=normalized_category,
            canonical_hint=hint, maintainer_hint=raw.get("maintainer_hint"),
            source_observation_id=source_observation["id"],
            source_notes=raw.get("source_notes", ""),  # claims-integrity: carried verbatim, never rewritten
        )

        # Step 9: epistemic-state review -- fail closed if a source packet
        # somehow tries to assert a stronger-than-floor state for itself.
        if not schema.freshly_ingested_candidate_is_at_epistemic_floor(candidate):
            raise IngestError(
                f"candidate {raw['observed_name']!r} did not start at the mission's "
                f"required epistemic floor -- refusing to trust a self-asserted stronger state"
            )

        errors = schema.validate_capability_candidate(candidate)
        if errors:
            raise IngestError(f"CapabilityCandidate failed validation: {errors}")

        candidates.append(candidate)

    # Step 10: claims-integrity review -- every free-text source_notes
    # value must be present verbatim in the stored candidate object (not
    # summarized, reworded, or dropped) -- checked structurally here
    # rather than merely asserted.
    for raw, candidate in zip(candidates_raw, candidates):
        expected_notes = raw.get("source_notes", "")
        if candidate["source_notes"] != expected_notes:
            raise IngestError(
                f"claims-integrity violation: source_notes for {raw['observed_name']!r} "
                f"were altered during ingestion"
            )

    _record(
        "HASH", artifact_sha256=digest, state="CANDIDATES_EXTRACTED",
        source_observation_id=source_observation["id"], candidate_count=len(candidates),
        candidate_ids=[c["id"] for c in candidates],
    )
    return source_observation, candidates
