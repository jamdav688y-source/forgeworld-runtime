"""Governed ingestion of the AUTHORITATIVE FW-CAP-DISPATCH-004 packet
(capability_dispatch/intake/FW-CAP-DISPATCH-004.json/.md, committed
2026-08-20 by the repository owner, sha256-verified independently in
evidence/FW-CAP-DISPATCH-004/candidate_import_report.json).

This is a SEPARATE parser from ingest.py's ingest_candidate_packet(),
which now serves the synthetic TEST_FIXTURE packet only
(capability_dispatch/fixtures/FW-CAP-DISPATCH-004.synthetic.json) --
the two packets are shaped differently:

  synthetic (TEST_FIXTURE):  {"candidate_count": N, "candidates": [
                                 {"observed_name", "observed_category",
                                  "canonical_hint", "maintainer_hint",
                                  "source_notes"}, ...]}
  authoritative (real):      {"capability_candidates": [
                                 {"name", "category", "canonical_hint"}, ...],
                               "source_observations": [...],
                               "strategy_signals": [...],
                               "dispatch_contract": {...}}
                              -- no candidate_count field at all; canonical
                              hints arrive as bare "github.com/owner/repo"
                              strings, not well-formed URLs.

Per the mission's explicit instruction ("Do not silently repair source
data... preserve the original observation value, record the normalized
value separately, state the normalization method"): candidate_count is
DERIVED (len(capability_candidates)) and stated as derived, never assumed
present; canonical_hint is preserved exactly as observed and a SEPARATE
canonical_hint_normalized field records the https://-prefixed form, with
canonical_hint_normalization_method stating exactly what was done.

Identity resolution for every one of these 42 real candidates is
performed with an EMPTY FixtureIdentityResolver (see run in
evidence/FW-CAP-DISPATCH-004/identity_resolution_report.json): this proof
stays fully offline and performs no live GitHub/registry API lookup, so
every candidate resolves UNAVAILABLE, not VERIFIED -- this is the honest,
correct outcome given the constraint, stated explicitly by the artifact's
own .md file ("Canonical identity resolution: incomplete"), not a
limitation of this ingester.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

from whatsapp.src import ledger as wa_ledger

from . import ingest, schema
from .common import now_iso, sha256_hex
from .ingest import IngestError, _normalize_name, detect_media_type

# Real packet's category vocabulary -> lowercase normalized form matching
# overlap.py's CATEGORY_FUNCTION_TAGS keys added for this packet.
_REAL_CATEGORY_NORMALIZATION = {
    "HARNESS": "harness", "SKILL": "skill", "APP_PLATFORM": "app_platform",
    "CONNECTOR_CATALOG": "connector_catalog", "TOOL_OR_APP": "tool_or_app",
    "PROMPT_LIBRARY": "prompt_library", "PROMPT_OR_OPTIMIZATION": "prompt_or_optimization",
    "SECURITY_SKILL": "security_skill",
}


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch",
        "stage": stage,
        "record_class": "AUTHORITATIVE_INGESTION",  # never TEST_FIXTURE
        "recorded_at": now_iso(),
        **fields,
    })


def _normalize_category(raw_category: str) -> str:
    return _REAL_CATEGORY_NORMALIZATION.get(raw_category, raw_category.lower())


def _normalize_canonical_hint(raw_hint):
    """Returns (normalized_value, method). Never raises on a non-URL raw
    hint -- this packet's hints are routinely bare domain+path strings."""
    if raw_hint is None:
        return None, ""
    try:
        parsed = urlparse(raw_hint)
    except (ValueError, AttributeError):
        return None, "unparseable_left_as_none"
    if parsed.scheme and parsed.netloc:
        return raw_hint, "already_well_formed"
    # Bare "github.com/owner/repo"-shaped string: assume https, state so.
    return f"https://{raw_hint}", "assumed_https_scheme_prepended_to_bare_domain_path"


def ingest_authoritative_packet(json_path, md_path, capture_source: str) -> dict:
    """CAPTURE + HASH + validation for both real files. Returns
    {"source_observation", "candidates", "md_source_observation",
     "strategy_signals_raw", "dispatch_contract_raw"}. Raises IngestError
    (fail closed) on any validation failure."""
    json_path = Path(json_path)
    md_path = Path(md_path)
    for p in (json_path, md_path):
        if not p.is_file():
            raise IngestError(f"authoritative source file does not exist: {p}")

    json_bytes = json_path.read_bytes()
    md_bytes = md_path.read_bytes()
    json_digest = sha256_hex(json_bytes)
    md_digest = sha256_hex(md_bytes)

    _record("CAPTURE", artifact_sha256=json_digest, source_path=str(json_path), state="RECEIVED")
    _record("CAPTURE", artifact_sha256=md_digest, source_path=str(md_path), state="RECEIVED")

    for data, digest, name in ((json_bytes, json_digest, json_path.name), (md_bytes, md_digest, md_path.name)):
        ingest.ARTIFACT_STORE.mkdir(parents=True, exist_ok=True)
        stored_path = ingest.ARTIFACT_STORE / f"{digest}{Path(name).suffix}"
        if not stored_path.exists():
            stored_path.write_bytes(data)
        _record("HASH", artifact_sha256=digest, stored_path=str(stored_path), state="STORED")

    detected_media_type = detect_media_type(json_bytes)
    if detected_media_type != "application/json":
        raise IngestError(
            f"{json_path.name!r} was detected as {detected_media_type!r} by content, "
            f"not application/json -- refusing to ingest it as the authoritative packet"
        )

    try:
        packet = json.loads(json_bytes)
    except json.JSONDecodeError as e:
        raise IngestError(f"authoritative JSON artifact is not valid JSON: {e}") from e

    for field in ("artifact_id", "capability_candidates"):
        if field not in packet:
            raise IngestError(f"authoritative packet missing required field: {field}")
    if "FW-CAP-DISPATCH-004" not in packet["artifact_id"]:
        raise IngestError(f"artifact_id {packet['artifact_id']!r} does not reference FW-CAP-DISPATCH-004")

    candidates_raw = packet["capability_candidates"]
    derived_candidate_count = len(candidates_raw)  # no candidate_count field in this packet shape -- derived, stated as such

    seen_names = set()
    for c in candidates_raw:
        if "name" not in c:
            raise IngestError(f"candidate missing required field 'name': {c!r}")
        key = c["name"].lower()
        if key in seen_names:
            raise IngestError(f"duplicate candidate name (case-insensitive): {c['name']!r}")
        seen_names.add(key)

    source_observation = schema.new_source_observation(
        artifact_id=packet["artifact_id"], artifact_sha256=json_digest, media_type=detected_media_type,
        filename=json_path.name, file_size_bytes=len(json_bytes), candidate_count=derived_candidate_count,
        capture_source=capture_source,
        source_notes=(
            f"candidate_count derived as len(capability_candidates)={derived_candidate_count} "
            f"-- the source packet declares no candidate_count field of its own. "
            f"title={packet.get('title')!r} status={packet.get('status')!r}"
        ),
    )
    errors = schema.validate_source_observation(source_observation)
    if errors:
        raise IngestError(f"SourceObservation failed validation: {errors}")

    md_source_observation = schema.new_source_observation(
        artifact_id=packet["artifact_id"], artifact_sha256=md_digest, media_type="text/markdown",
        filename=md_path.name, file_size_bytes=len(md_bytes), candidate_count=0,
        capture_source=capture_source, source_notes="companion narrative artifact, no candidates of its own",
    )
    errors = schema.validate_source_observation(md_source_observation)
    if errors:
        raise IngestError(f"MD SourceObservation failed validation: {errors}")

    candidates = []
    for raw in candidates_raw:
        raw_hint = raw.get("canonical_hint")
        normalized_hint, hint_method = _normalize_canonical_hint(raw_hint)
        observed_category = raw.get("category", "UNKNOWN")
        normalized_category = _normalize_category(observed_category)

        candidate = schema.new_capability_candidate(
            artifact_id=packet["artifact_id"], artifact_sha256=json_digest,
            observed_name=raw["name"], normalized_name=_normalize_name(raw["name"]),
            observed_category=observed_category, normalized_category=normalized_category,
            canonical_hint=raw_hint,  # raw, unmodified, may be None or a bare domain string
            maintainer_hint=None, source_observation_id=source_observation["id"],
            source_notes="",  # this packet carries no per-candidate free text -- none fabricated
            canonical_hint_normalized=normalized_hint, canonical_hint_normalization_method=hint_method,
        )
        if not schema.freshly_ingested_candidate_is_at_epistemic_floor(candidate):
            raise IngestError(f"candidate {raw['name']!r} did not start at the required epistemic floor")
        errors = schema.validate_capability_candidate(candidate)
        if errors:
            raise IngestError(f"CapabilityCandidate failed validation for {raw['name']!r}: {errors}")
        candidates.append(candidate)

    _record(
        "HASH", artifact_sha256=json_digest, state="CANDIDATES_EXTRACTED",
        source_observation_id=source_observation["id"], candidate_count=len(candidates),
        candidate_ids=[c["id"] for c in candidates],
    )

    return {
        "source_observation": source_observation,
        "md_source_observation": md_source_observation,
        "candidates": candidates,
        "strategy_signals_raw": packet.get("strategy_signals", []),
        "dispatch_contract_raw": packet.get("dispatch_contract", {}),
        "source_observations_raw": packet.get("source_observations", []),
    }
