"""Local OCR via Tesseract (through pytesseract). No cloud calls.

Original images are never modified: preprocessing happens on an in-memory
derivative only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image, ImageOps, ImageEnhance
except ImportError:  # pragma: no cover - Pillow is a required dependency
    Image = None  # type: ignore

try:
    import pytesseract
    from pytesseract import Output
except ImportError:  # pragma: no cover - pytesseract is a required dependency
    pytesseract = None  # type: ignore
    Output = None  # type: ignore

OCR_STATE_PASS = "PASS"
OCR_STATE_EMPTY = "EMPTY"
OCR_STATE_FAILED = "FAILED"
OCR_STATE_TIMEOUT = "TIMEOUT"
OCR_STATE_UNUSABLE = "UNUSABLE"
OCR_STATE_CORRECTED = "CORRECTED"

VALID_OCR_STATES = {
    OCR_STATE_PASS,
    OCR_STATE_EMPTY,
    OCR_STATE_FAILED,
    OCR_STATE_TIMEOUT,
    OCR_STATE_UNUSABLE,
    OCR_STATE_CORRECTED,
}


@dataclass
class OcrResult:
    raw_text: str
    normalized_text: str
    engine_name: str
    engine_version: str
    language: str
    extracted_at: str
    success_state: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    confidence: float | None = None
    duration_ms: int = 0


def _engine_version() -> str:
    if pytesseract is None:
        return "unavailable"
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return "unknown"


def _build_derivative(image_path: Path, max_dimension: int) -> "Image.Image":
    """Build a bounded, grayscale, contrast-enhanced derivative for OCR.

    The original file on disk is opened read-only and never written to.
    """
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")

    width, height = img.size
    largest = max(width, height)
    if largest > max_dimension:
        scale = max_dimension / float(largest)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)

    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.3)
    return img


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _extract_confidence(derivative: "Image.Image", language: str, psm: int, timeout: int) -> float | None:
    try:
        data = pytesseract.image_to_data(
            derivative,
            lang=language,
            config=f"--psm {psm}",
            timeout=timeout,
            output_type=Output.DICT,
        )
    except Exception:
        return None
    confidences = [float(c) for c in data.get("conf", []) if _is_positive_conf(c)]
    if not confidences:
        return None
    return round(sum(confidences) / len(confidences), 2)


def _is_positive_conf(value: object) -> bool:
    try:
        return float(value) >= 0
    except (TypeError, ValueError):
        return False


def run_ocr(
    image_path: Path,
    language: str = "eng",
    timeout_seconds: int = 45,
    max_dimension: int = 2200,
    psm: int = 6,
) -> OcrResult:
    """Run OCR on image_path and return an OcrResult. Never raises for
    ordinary OCR failures -- those are captured in success_state/errors so
    callers can persist a full lineage record either way.
    """
    started = time.monotonic()
    extracted_at = datetime.now(timezone.utc).isoformat()
    engine_version = _engine_version()

    if Image is None or pytesseract is None:
        return OcrResult(
            raw_text="",
            normalized_text="",
            engine_name="tesseract",
            engine_version="unavailable",
            language=language,
            extracted_at=extracted_at,
            success_state=OCR_STATE_FAILED,
            errors=["Pillow or pytesseract is not installed in this environment."],
            duration_ms=0,
        )

    warnings: list[str] = []
    errors: list[str] = []

    try:
        derivative = _build_derivative(image_path, max_dimension)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return OcrResult(
            raw_text="",
            normalized_text="",
            engine_name="tesseract",
            engine_version=engine_version,
            language=language,
            extracted_at=extracted_at,
            success_state=OCR_STATE_FAILED,
            errors=[f"Failed to prepare OCR derivative: {exc}"],
            duration_ms=duration_ms,
        )

    try:
        raw_text = pytesseract.image_to_string(
            derivative,
            lang=language,
            config=f"--psm {psm}",
            timeout=timeout_seconds,
        )
    except RuntimeError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        message = str(exc).lower()
        state = OCR_STATE_TIMEOUT if "timeout" in message else OCR_STATE_FAILED
        return OcrResult(
            raw_text="",
            normalized_text="",
            engine_name="tesseract",
            engine_version=engine_version,
            language=language,
            extracted_at=extracted_at,
            success_state=state,
            errors=[str(exc)],
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return OcrResult(
            raw_text="",
            normalized_text="",
            engine_name="tesseract",
            engine_version=engine_version,
            language=language,
            extracted_at=extracted_at,
            success_state=OCR_STATE_FAILED,
            errors=[f"Tesseract invocation failed: {exc}"],
            duration_ms=duration_ms,
        )

    confidence = _extract_confidence(derivative, language, psm, timeout_seconds)
    normalized = _normalize_text(raw_text)
    duration_ms = int((time.monotonic() - started) * 1000)

    if not normalized:
        state = OCR_STATE_EMPTY
        warnings.append("OCR completed but produced no readable text.")
    else:
        state = OCR_STATE_PASS

    return OcrResult(
        raw_text=raw_text,
        normalized_text=normalized,
        engine_name="tesseract",
        engine_version=engine_version,
        language=language,
        extracted_at=extracted_at,
        success_state=state,
        warnings=warnings,
        errors=errors,
        confidence=confidence,
        duration_ms=duration_ms,
    )
