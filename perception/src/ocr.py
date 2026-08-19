"""OCR + visual-fingerprint stages: provider-neutral text extraction, plus
orchestration that turns both into ExtractedSignal objects.

Provider-neutral by the same reasoning as whatsapp/src/classify.py's
documented-but-unwired AI-routing extension point: no OCR/vision credentials
are confirmed for this channel, so the default path is a deterministic,
auditable mock -- not a fabricated capability. `CloudOCRProvider` below is
the real hook point for a future wired provider; it raises NotImplementedError
today rather than silently returning made-up text.

The acceptance tests require this explicitly: "Offline tests use deterministic
fixtures and mocked provider responses" -- FixtureOCRProvider *is* that
mock, keyed by image_sha256 so a known fixture always yields the same
extracted text, and it is labeled as a mock everywhere it appears (provider
name is literally "mock:fixture_ocr", never something that could be mistaken
for a real vision model).
"""
from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso
from .imaging import perceptual_fingerprint


class OCRProvider:
    """Duck-typed interface every OCR provider implements."""
    name = "unset"
    prompt_version = None

    def run(self, image_bytes: bytes, image_sha256: str) -> dict:
        """Returns a raw response dict with at least {"text": str, "confidence": float}."""
        raise NotImplementedError


class FixtureOCRProvider(OCRProvider):
    """Deterministic offline mock: image_sha256 -> canned OCR result.

    This is the only OCR provider actually exercised in this proof -- it is
    a fixture double, not a text-recognition engine, and is named
    accordingly so no report or ledger entry could be misread as a claim of
    real OCR capability.
    """
    name = "mock:fixture_ocr"
    prompt_version = "fixture-v1"

    def __init__(self, fixture_map: dict):
        self._fixtures = dict(fixture_map)

    def run(self, image_bytes: bytes, image_sha256: str) -> dict:
        if image_sha256 not in self._fixtures:
            return {"text": "", "confidence": 0.0, "note": "no fixture registered for this sha256"}
        entry = self._fixtures[image_sha256]
        return {"text": entry["text"], "confidence": entry.get("confidence", 0.9)}


class CloudOCRProvider(OCRProvider):
    """Documented extension point for a real OCR/vision provider (mission
    Section on 'provider/model where applicable'). Not wired: no credentials
    for any such service were confirmed available in this environment, and
    this proof stays fully offline per the mission's own constraint
    ('Operate offline wherever possible'). Wiring this in later means
    filling in `run()` -- the ExtractedSignal envelope, ledger recording,
    and fail-closed error handling below all already work with any
    OCRProvider, this one included, without further changes.
    """
    name = "unwired:cloud_ocr"
    prompt_version = None

    def run(self, image_bytes: bytes, image_sha256: str) -> dict:
        raise NotImplementedError(
            "CloudOCRProvider is a documented extension point, not a wired provider -- "
            "no OCR/vision credentials are configured for this channel."
        )


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def extract_ocr_signal(observation: dict, image_bytes: bytes, provider: OCRProvider) -> dict:
    """OCR stage. Fails closed: a provider error surfaces as an exception,
    never as a fabricated empty-but-'extracted' signal."""
    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]

    raw = provider.run(image_bytes, image_sha256)
    _record(
        "OCR", image_sha256=image_sha256, observation_id=observation["id"],
        provider=provider.name, state="RAN",
    )

    signal = schema.new_extracted_signal(
        image_id=image_id, image_sha256=image_sha256, signal_type="ocr_text",
        value=raw.get("text", ""), extraction_method="ocr",
        provider=provider.name, confidence=raw.get("confidence", 0.0),
        observation_id=observation["id"], prompt_version=provider.prompt_version,
        raw_response=raw,
    )
    errors = schema.validate_extracted_signal(signal)
    if errors:
        raise ValueError(f"OCR ExtractedSignal failed validation: {errors}")

    _record(
        "OCR", image_sha256=image_sha256, observation_id=observation["id"],
        signal_id=signal["id"], state="SIGNAL_CREATED",
    )
    return signal


def extract_fingerprint_signal(observation: dict, image_bytes: bytes) -> dict:
    """FINGERPRINT stage. Pure deterministic computation (dHash), not a
    model -- provider is left None and confidence is 1.0, matching
    VisualObservation's own reasoning: possessing the bytes and computing a
    fixed function of them is a certain fact, not a probabilistic one."""
    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]

    fingerprint = perceptual_fingerprint(image_bytes)
    _record(
        "FINGERPRINT", image_sha256=image_sha256, observation_id=observation["id"],
        fingerprint=fingerprint, state="COMPUTED",
    )

    signal = schema.new_extracted_signal(
        image_id=image_id, image_sha256=image_sha256, signal_type="visual_fingerprint",
        value=fingerprint, extraction_method="dhash_8x8",
        provider=None, confidence=1.0, observation_id=observation["id"],
    )
    errors = schema.validate_extracted_signal(signal)
    if errors:
        raise ValueError(f"fingerprint ExtractedSignal failed validation: {errors}")

    _record(
        "FINGERPRINT", image_sha256=image_sha256, observation_id=observation["id"],
        signal_id=signal["id"], state="SIGNAL_CREATED",
    )
    return signal
