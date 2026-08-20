"""Thin envelope adapter over perception.src.common.

Reuses perception's build_envelope()/validate_envelope() logic directly --
the minimum-fields envelope this mission requires (stable ID, schema
version, timestamp, source ID, source hash, extraction method, provider,
prompt version, raw-response hash, confidence, evidence references,
validation status, human-review status, contradiction state, temporal
validity) is identical to Proof 001's. Nothing here re-implements that
logic; see perception/governance/00_DISCOVERY_REPORT.md-style reasoning,
now applied one level up: capability_dispatch reuses perception exactly
the way perception reused whatsapp/governance.

The only change is field naming: perception's envelope hardcodes
source_image_id/source_image_sha256 because VisualObservation genuinely is
about images. A capability-candidate observation is not an image, so this
module renames those two keys to source_artifact_id/source_artifact_sha256
immediately after construction. Every other field is untouched.
"""
from perception.src import common as perception_common

SCHEMA_VERSION = perception_common.SCHEMA_VERSION
HEX64 = perception_common.HEX64
HUMAN_REVIEW_STATUSES = perception_common.HUMAN_REVIEW_STATUSES
CONTRADICTION_STATES = perception_common.CONTRADICTION_STATES

new_id = perception_common.new_id
now_iso = perception_common.now_iso
sha256_hex = perception_common.sha256_hex
hash_raw_response = perception_common.hash_raw_response
new_temporal_validity = perception_common.new_temporal_validity

ENVELOPE_FIELDS = [
    "id", "schema_version", "created_at", "source_artifact_id", "source_artifact_sha256",
    "extraction_method", "provider", "prompt_version", "raw_response_hash",
    "confidence", "evidence_references", "validation_status", "human_review_status",
    "contradiction_state", "temporal_validity",
]


def build_envelope(
    id_prefix: str, source_artifact_id, source_artifact_sha256, extraction_method: str,
    validation_status: str, **kwargs,
) -> dict:
    envelope = perception_common.build_envelope(
        id_prefix, source_artifact_id, source_artifact_sha256, extraction_method,
        validation_status, **kwargs,
    )
    envelope["source_artifact_id"] = envelope.pop("source_image_id")
    envelope["source_artifact_sha256"] = envelope.pop("source_image_sha256")
    return envelope


def validate_envelope(obj: dict) -> list:
    translated = dict(obj)
    if "source_artifact_id" in translated:
        translated["source_image_id"] = translated.pop("source_artifact_id")
    if "source_artifact_sha256" in translated:
        translated["source_image_sha256"] = translated.pop("source_artifact_sha256")
    errors = perception_common.validate_envelope(translated)
    return [e.replace("source_image_sha256", "source_artifact_sha256") for e in errors]
