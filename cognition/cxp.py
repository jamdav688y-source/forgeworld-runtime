"""FW-CXP-R1-IMPLEMENTATION-001: Cognitive Exchange Protocol v1 -- record
schema, validation, identity and lineage rules.

CXP is an INFORMATION-EXCHANGE layer. Nothing in this module (or in
cognition.exchange) grants, implies, or carries execution authority: it
imports nothing from fabric/ or substrate/, it has no execute/authorize
method anywhere, and a payload that tries to smuggle authority-shaped
fields (grants, authority contexts, keys) is rejected outright
(AUTHORITY_FIELD_FORBIDDEN). Every record answers
grants_execution_authority -> False.

REUSED, not reimplemented: evidence_envelope.trajectory's PROVENANCE_KINDS
vocabulary (the same one substrate/ reuses), and evidence_envelope's
validate_mission_id() for emitter/consumer identifiers.

THREE INDEPENDENT EPISTEMIC DIMENSIONS, never collapsed into one:
    representation  QUOTATION | PARAPHRASE | INFERENCE | HYPOTHESIS |
                    SIMULATION | DRAMATIZATION          (what form it takes)
    evidence        NONE | SINGLE_SOURCE | INDEPENDENT_SOURCES |
                    EXPERIMENT_REFERENCE                (what backs it)
    verification    UNVERIFIED | CONTESTED | VERIFIED | REFUTED
                                                        (what was checked)

FIVE DISTINCT IDENTITIES (all sha256 over strict canonical JSON, each
under its own domain-separation tag so no two can ever collide):
    source_id      = H(source_type, locator)
                     WHERE a thing came from. independence_key (default:
                     the source_id itself) is what independence is
                     counted on -- declared by the caller, so only as
                     trustworthy as that declaration.
    content_id     = H(kind, representation, payload)
                     WHAT is said. The same statement from two different
                     sources has the same content_id.
    record_id      = H(every record field except the occurrence block)
                     = content_id + provenance + evidence + verification
                     + privacy + sources + derived_from + verification_ref
                     + consent_ref + schema_version.
                     THIS assertion, from THIS lineage. The same statement
                     from two distinct sources yields two record_ids, so
                     independent observations are never collapsed into one.
                     This is the idempotency key for consumer processing.
    occurrence_id  = H(record_id, emitter_id, observed_at)
                     ONE sighting/delivery of a record. Re-observing the
                     same record later is a new occurrence of the same
                     record; replaying the exact same event is the same
                     occurrence.
    correlation_id / causation_id
                     Carried on the occurrence only, never part of any
                     identity: they describe the conversation an event
                     arrived in, not what it asserts.
No wall-clock time and no random value participates in any identity.
observed_at participates in occurrence_id only, deliberately: it is the
caller-supplied time of the sighting, which is what distinguishes two
sightings. Strings are NOT Unicode-normalized before hashing (normalizing
would silently alter quotations), so NFC and NFD spellings of the same text
are different content.

LINEAGE (no derivative may masquerade as independent evidence):
  - Root kinds (OBSERVATION, VERIFICATION_RESULT) cite their own sources
    and derive from nothing.
  - Derived kinds (CLAIM, CONTRADICTION, LENS_OUTPUT) cite parents (derived_from) and NO sources of
    their own; their root sources are COMPUTED as the union of their
    parents' root sources, never supplied by the caller.
  - The evidence ceiling is computed from the root sources: 0 independence
    keys -> NONE, 1 -> SINGLE_SOURCE, >=2 -> INDEPENDENT_SOURCES,
    EXPERIMENT_REFERENCE only with an `experiment` root source. Ten
    paraphrases of one commit still have one root and stay SINGLE_SOURCE.
  - A derived record's evidence may additionally never exceed its
    strongest parent's (a transformation cannot increase evidence), and its
    privacy may never be lower than its most restrictive parent's.
  - Verification is never inherited. VERIFIED/REFUTED requires a
    verification_ref naming an already-accepted VERIFICATION_RESULT whose
    target_content_id is this record's content_id and whose outcome
    matches. SIMULATION and DRAMATIZATION can never be VERIFIED.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evidence_envelope import envelope  # noqa: E402

# Same flat-import workaround substrate/interface.py and
# evidence_envelope/tests/test_trajectory.py use for trajectory.py.
_EVIDENCE_ENVELOPE_DIR = _ROOT / "evidence_envelope"
if str(_EVIDENCE_ENVELOPE_DIR) not in sys.path:
    sys.path.insert(0, str(_EVIDENCE_ENVELOPE_DIR))
import trajectory as _trajectory  # noqa: E402

PROVENANCE_KINDS = _trajectory.PROVENANCE_KINDS
OBSERVED = _trajectory.OBSERVED
DERIVED = _trajectory.DERIVED
HUMAN_ASSERTED = _trajectory.HUMAN_ASSERTED
SYSTEM_ASSERTED = _trajectory.SYSTEM_ASSERTED
UNVERIFIED_INTERPRETATION = _trajectory.UNVERIFIED_INTERPRETATION
AUTHORIZED_CONCLUSION = _trajectory.AUTHORIZED_CONCLUSION

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1,)

# --- kinds -----------------------------------------------------------------
KIND_OBSERVATION = "OBSERVATION"
KIND_CLAIM = "CLAIM"
KIND_VERIFICATION_RESULT = "VERIFICATION_RESULT"
KIND_CONTRADICTION = "CONTRADICTION"
KIND_LENS_OUTPUT = "LENS_OUTPUT"
ENABLED_KINDS = (KIND_OBSERVATION, KIND_CLAIM, KIND_VERIFICATION_RESULT, KIND_CONTRADICTION, KIND_LENS_OUTPUT)
# Named so the vocabulary is stable, but refused until a later slice defines
# their payload schemas (KIND_NOT_ENABLED).
RESERVED_KINDS = (
    "HYPOTHESIS", "EXPERIMENT", "EPISODE_CANDIDATE",
    "AUDIENCE_QUESTION", "COMMERCIAL_SIGNAL", "OUTCOME_MEASUREMENT",
)
MAX_CONTRADICTION_CLAIMS = 16
MAX_RESOLUTION_CONDITIONS = 16

# --- lens outputs (R3) -----------------------------------------------------
LENS_IDS = ("MUSE", "SCIENTIST", "ARCHITECT", "CHALLENGER", "STORYWEAVER", "EMPATH", "CATALYST")
Q_READY_FOR_EPISODE = "ready_for_episode_planning"
Q_CLAIM_ESTABLISHED = "claim_established"
Q_NEEDS_EXPERIMENT = "needs_experiment"
LENS_QUESTIONS = (Q_CLAIM_ESTABLISHED, Q_NEEDS_EXPERIMENT, Q_READY_FOR_EPISODE)
POS_SUPPORT = "SUPPORT"
POS_OPPOSE = "OPPOSE"
POS_UNCERTAIN = "UNCERTAIN"
POSITIONS = (POS_SUPPORT, POS_OPPOSE, POS_UNCERTAIN)
MAX_LENS_LIST_ITEMS = 32
_LENS_VERSION_PATTERN = re.compile(r"^[0-9]{1,6}$")
_LENS_OUTPUT_KEYS = frozenset({"lens_id", "lens_version", "statement", "positions", "uncertainties",
                               "unsupported_claims", "next_action", "details"})
_ROOT_KINDS = (KIND_OBSERVATION, KIND_VERIFICATION_RESULT)

# --- representation --------------------------------------------------------
REP_QUOTATION = "QUOTATION"
REP_PARAPHRASE = "PARAPHRASE"
REP_INFERENCE = "INFERENCE"
REP_HYPOTHESIS = "HYPOTHESIS"
REP_SIMULATION = "SIMULATION"
REP_DRAMATIZATION = "DRAMATIZATION"
REPRESENTATIONS = (REP_QUOTATION, REP_PARAPHRASE, REP_INFERENCE, REP_HYPOTHESIS, REP_SIMULATION, REP_DRAMATIZATION)
_NEVER_VERIFIABLE_REPRESENTATIONS = (REP_SIMULATION, REP_DRAMATIZATION)

# --- evidence (ordered weakest -> strongest) -------------------------------
EV_NONE = "NONE"
EV_SINGLE_SOURCE = "SINGLE_SOURCE"
EV_INDEPENDENT_SOURCES = "INDEPENDENT_SOURCES"
EV_EXPERIMENT_REFERENCE = "EXPERIMENT_REFERENCE"
EVIDENCE_CLASSES = (EV_NONE, EV_SINGLE_SOURCE, EV_INDEPENDENT_SOURCES, EV_EXPERIMENT_REFERENCE)

# --- verification ----------------------------------------------------------
VER_UNVERIFIED = "UNVERIFIED"
VER_CONTESTED = "CONTESTED"
VER_VERIFIED = "VERIFIED"
VER_REFUTED = "REFUTED"
VERIFICATION_STATES = (VER_UNVERIFIED, VER_CONTESTED, VER_VERIFIED, VER_REFUTED)
_REQUIRES_VERIFICATION_REF = (VER_VERIFIED, VER_REFUTED)

# --- privacy (ordered least -> most restrictive) ---------------------------
PRIV_PUBLIC = "PUBLIC"
PRIV_INTERNAL = "INTERNAL"
PRIV_PERSONAL = "PERSONAL"
PRIV_RESTRICTED = "RESTRICTED"
PRIVACY_CLASSES = (PRIV_PUBLIC, PRIV_INTERNAL, PRIV_PERSONAL, PRIV_RESTRICTED)

SOURCE_TYPE_EXPERIMENT = "experiment"
SOURCE_TYPES = (
    "git_commit", "repository_file", "test_run", "document", "human_statement",
    SOURCE_TYPE_EXPERIMENT, "synthetic_fixture",
)

# Authority-shaped keys refused anywhere in a payload or consumer output
# (compared case-insensitively). CXP carries information, never permission.
FORBIDDEN_AUTHORITY_KEYS = frozenset({
    "authority", "authority_context", "authorization", "grant", "grants", "grant_id",
    "granted_capability_ids", "capability_request", "execute", "execution_authority",
    "authkey", "integrity_key", "relationship_key", "pairing", "credential", "credentials",
    "password", "token", "secret",
})

MAX_PAYLOAD_BYTES = 64 * 1024
MAX_STATEMENT_CHARS = 8000
MAX_LOCATOR_CHARS = 2048
MAX_NESTING_DEPTH = 32

# --- error codes -----------------------------------------------------------
E_MALFORMED = "SCHEMA_MALFORMED"
E_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
E_KIND_NOT_ENABLED = "KIND_NOT_ENABLED"
E_KIND_RULE = "KIND_RULE_VIOLATION"
E_PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
E_AUTHORITY_FIELD_FORBIDDEN = "AUTHORITY_FIELD_FORBIDDEN"
E_PRIVACY_CONSENT_REQUIRED = "PRIVACY_CONSENT_REQUIRED"
E_PRIVACY_DOWNGRADE = "PRIVACY_DOWNGRADE"
E_PRIVACY_PERSISTENCE_UNSUPPORTED = "PRIVACY_PERSISTENCE_UNSUPPORTED"
E_LINEAGE_UNRESOLVED = "LINEAGE_UNRESOLVED"
E_EVIDENCE_INFLATION = "EVIDENCE_INFLATION"
E_VERIFICATION_UNSUPPORTED = "VERIFICATION_UNSUPPORTED"
E_ERASED = "RECORD_ERASED"
E_DUPLICATE_CONTRADICTION = "DUPLICATE_CONTRADICTION"
ERROR_CODES = (
    E_MALFORMED, E_VERSION_UNSUPPORTED, E_KIND_NOT_ENABLED, E_KIND_RULE, E_PAYLOAD_TOO_LARGE,
    E_AUTHORITY_FIELD_FORBIDDEN, E_PRIVACY_CONSENT_REQUIRED, E_PRIVACY_DOWNGRADE,
    E_PRIVACY_PERSISTENCE_UNSUPPORTED, E_LINEAGE_UNRESOLVED, E_EVIDENCE_INFLATION,
    E_VERIFICATION_UNSUPPORTED, E_ERASED, E_DUPLICATE_CONTRADICTION,
)

_ID_PREFIXES = {"source": "cxp-src-", "content": "cxp-content-", "record": "cxp-rec-", "occurrence": "cxp-occ-",
                "result": "cxp-res-", "brief": "cxp-brief-", "assembly": "cxp-asm-"}
_RECORD_ID_PATTERN = re.compile(r"^cxp-rec-[0-9a-f]{64}$")
_CONTENT_ID_PATTERN = re.compile(r"^cxp-content-[0-9a-f]{64}$")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")

_TOP_LEVEL_KEYS = frozenset({
    "schema_version", "kind", "representation", "evidence", "verification", "provenance", "privacy",
    "payload", "sources", "derived_from", "verification_ref", "consent_ref", "occurrence",
})
_OCCURRENCE_KEYS = frozenset({"emitter_id", "observed_at", "correlation_id", "causation_id"})
_SOURCE_KEYS = frozenset({"source_type", "locator", "independence_key"})


class CXPError(Exception):
    """A rejected event. `code` is one of ERROR_CODES; `detail` never
    echoes payload content, only structural information."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# strict canonical serialization + domain-separated digests
# ---------------------------------------------------------------------------

def _check_canonicalizable(obj, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise CXPError(E_MALFORMED, f"nesting deeper than {MAX_NESTING_DEPTH}")
    if obj is None or isinstance(obj, (bool, str)):
        return
    if isinstance(obj, int):
        return
    if isinstance(obj, float):
        # Floats have several textual forms for one value (1.0 / 1 / 1e0) and
        # NaN/inf are not JSON; refusing them keeps identity unambiguous.
        raise CXPError(E_MALFORMED, "floats are not canonicalizable; encode as string or integer")
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _check_canonicalizable(item, depth + 1)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise CXPError(E_MALFORMED, "object keys must be strings")
            _check_canonicalizable(value, depth + 1)
        return
    raise CXPError(E_MALFORMED, f"value of type {type(obj).__name__} is not canonicalizable")


def canonical_bytes(obj) -> bytes:
    """Strict canonical JSON: sorted keys, no insignificant whitespace,
    UTF-8, no floats, no NaN, no non-JSON types (unlike
    envelope._canonical, which stringifies unknown types via default=str
    and so is not safe to hash as an identity)."""
    _check_canonicalizable(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest_id(domain: str, obj) -> str:
    prefix = _ID_PREFIXES[domain]
    h = hashlib.sha256()
    h.update(f"forgeworld.cxp.v1.{domain}".encode("ascii") + b"\x00")
    h.update(canonical_bytes(obj))
    return prefix + h.hexdigest()


def _find_forbidden_key(obj) -> Optional[str]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_AUTHORITY_KEYS:
                return key
            found = _find_forbidden_key(value)
            if found is not None:
                return found
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found = _find_forbidden_key(item)
            if found is not None:
                return found
    return None


def check_no_authority_fields(obj, what: str) -> None:
    key = _find_forbidden_key(obj)
    if key is not None:
        raise CXPError(E_AUTHORITY_FIELD_FORBIDDEN, f"{what} contains authority-shaped key {key!r}")


# ---------------------------------------------------------------------------
# object model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceRef:
    source_id: str
    source_type: str
    locator: str
    independence_key: str

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "source_type": self.source_type, "locator": self.locator,
                "independence_key": self.independence_key}


@dataclass(frozen=True)
class CognitiveRecord:
    """One validated CXP v1 assertion. Immutable; payload() returns a fresh
    copy on every call so no holder (e.g. one consumer) can alter what
    another sees."""

    schema_version: int
    kind: str
    representation: str
    evidence: str
    verification: str
    provenance: str
    privacy: str
    payload_json: str
    sources: tuple
    derived_from: tuple
    verification_ref: Optional[str]
    consent_ref: Optional[str]
    content_id: str
    record_id: str

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def payload(self) -> dict:
        return json.loads(self.payload_json)

    def identity_fields(self) -> dict:
        """Exactly the fields record_id is computed over."""
        return {
            "schema_version": self.schema_version, "content_id": self.content_id,
            "evidence": self.evidence, "verification": self.verification, "provenance": self.provenance,
            "privacy": self.privacy, "sources": [s.to_dict() for s in self.sources],
            "derived_from": list(self.derived_from), "verification_ref": self.verification_ref,
            "consent_ref": self.consent_ref,
        }

    def metadata(self) -> dict:
        """Durable, payload-free description of this record."""
        return {**self.identity_fields(), "kind": self.kind, "representation": self.representation,
                "record_id": self.record_id}


@dataclass(frozen=True)
class Occurrence:
    occurrence_id: str
    record_id: str
    emitter_id: str
    observed_at: str
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {"occurrence_id": self.occurrence_id, "record_id": self.record_id, "emitter_id": self.emitter_id,
                "observed_at": self.observed_at, "correlation_id": self.correlation_id,
                "causation_id": self.causation_id}


# ---------------------------------------------------------------------------
# structural parsing (no lineage lookup)
# ---------------------------------------------------------------------------

def _require_enum(raw: dict, key: str, allowed: tuple) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise CXPError(E_MALFORMED, f"{key} must be one of {allowed}")
    return value


def _optional_str(raw: dict, key: str, max_len: int = 256) -> Optional[str]:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise CXPError(E_MALFORMED, f"{key} must be a non-empty string of at most {max_len} chars, or null")
    return value


def _validate_identifier(value, what: str) -> str:
    try:
        return envelope.validate_mission_id(value)
    except envelope.EnvelopeError:
        raise CXPError(E_MALFORMED, f"{what} is not a valid identifier") from None


def _parse_schema_version(raw: dict) -> int:
    if "schema_version" not in raw:
        raise CXPError(E_MALFORMED, "schema_version is required")
    version = raw["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise CXPError(E_MALFORMED, "schema_version must be an integer")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise CXPError(E_VERSION_UNSUPPORTED, f"schema_version {version} not in {SUPPORTED_SCHEMA_VERSIONS}")
    return version


def _parse_payload(kind: str, payload) -> str:
    if not isinstance(payload, dict):
        raise CXPError(E_MALFORMED, "payload must be an object")
    check_no_authority_fields(payload, "payload")
    encoded = canonical_bytes(payload)
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise CXPError(E_PAYLOAD_TOO_LARGE, f"payload is {len(encoded)} bytes (max {MAX_PAYLOAD_BYTES})")

    if kind in (KIND_OBSERVATION, KIND_CLAIM):
        if set(payload) - {"statement", "subject"}:
            raise CXPError(E_MALFORMED, f"{kind} payload allows only 'statement' and 'subject'")
        statement = payload.get("statement")
        if not isinstance(statement, str) or not statement.strip() or len(statement) > MAX_STATEMENT_CHARS:
            raise CXPError(E_MALFORMED, f"{kind} payload.statement must be a non-empty string")
        if "subject" in payload and not (isinstance(payload["subject"], str) and payload["subject"]):
            raise CXPError(E_MALFORMED, f"{kind} payload.subject must be a non-empty string")
    elif kind == KIND_VERIFICATION_RESULT:
        if set(payload) != {"target_content_id", "outcome", "method"}:
            raise CXPError(E_MALFORMED, "VERIFICATION_RESULT payload requires exactly target_content_id, outcome, method")
        if not isinstance(payload["target_content_id"], str) or not _CONTENT_ID_PATTERN.match(payload["target_content_id"]):
            raise CXPError(E_MALFORMED, "VERIFICATION_RESULT target_content_id is not a content id")
        if payload["outcome"] not in (VER_VERIFIED, VER_REFUTED, VER_CONTESTED):
            raise CXPError(E_MALFORMED, "VERIFICATION_RESULT outcome must be VERIFIED, REFUTED or CONTESTED")
        if not isinstance(payload["method"], str) or not payload["method"]:
            raise CXPError(E_MALFORMED, "VERIFICATION_RESULT method must be a non-empty string")
    elif kind == KIND_CONTRADICTION:
        if set(payload) != {"claims", "resolution_conditions", "summary"}:
            raise CXPError(E_MALFORMED, "CONTRADICTION payload requires exactly claims, resolution_conditions, summary")
        claims = payload["claims"]
        if (not isinstance(claims, list) or not 2 <= len(claims) <= MAX_CONTRADICTION_CLAIMS
                or len(set(claims)) != len(claims)
                or not all(isinstance(c, str) and _RECORD_ID_PATTERN.match(c) for c in claims)):
            raise CXPError(E_MALFORMED, f"CONTRADICTION claims must be 2-{MAX_CONTRADICTION_CLAIMS} distinct record ids")
        if claims != sorted(claims):
            raise CXPError(E_MALFORMED, "CONTRADICTION claims must be sorted (one canonical form per claim set)")
        conditions = payload["resolution_conditions"]
        if (not isinstance(conditions, list) or not 1 <= len(conditions) <= MAX_RESOLUTION_CONDITIONS
                or not all(isinstance(c, str) and c.strip() and len(c) <= MAX_STATEMENT_CHARS for c in conditions)):
            raise CXPError(E_MALFORMED, "CONTRADICTION resolution_conditions must be 1-16 non-empty strings")
        if not isinstance(payload["summary"], str) or not payload["summary"].strip() or len(payload["summary"]) > MAX_STATEMENT_CHARS:
            raise CXPError(E_MALFORMED, "CONTRADICTION summary must be a non-empty string")
    elif kind == KIND_LENS_OUTPUT:
        _check_lens_payload(payload)
    return encoded.decode("utf-8")


def _short_strings(value, what: str) -> None:
    if (not isinstance(value, list) or len(value) > MAX_LENS_LIST_ITEMS
            or not all(isinstance(v, str) and v.strip() and len(v) <= MAX_STATEMENT_CHARS for v in value)):
        raise CXPError(E_MALFORMED, f"LENS_OUTPUT {what} must be a list of at most {MAX_LENS_LIST_ITEMS} non-empty strings")


def _check_lens_payload(payload: dict) -> None:
    """A lens output carries an interpretation, positions on a fixed set of
    questions, and its own doubts. It has no field for evidence, verification
    or authority: those are labels on the record, set and checked by CXP."""
    if set(payload) != _LENS_OUTPUT_KEYS:
        raise CXPError(E_MALFORMED, f"LENS_OUTPUT payload requires exactly {sorted(_LENS_OUTPUT_KEYS)}")
    if payload["lens_id"] not in LENS_IDS:
        raise CXPError(E_MALFORMED, f"LENS_OUTPUT lens_id must be one of {LENS_IDS}")
    if not isinstance(payload["lens_version"], str) or not _LENS_VERSION_PATTERN.match(payload["lens_version"]):
        raise CXPError(E_MALFORMED, "LENS_OUTPUT lens_version must be a short numeric string")
    statement = payload["statement"]
    if not isinstance(statement, str) or not statement.strip() or len(statement) > MAX_STATEMENT_CHARS:
        raise CXPError(E_MALFORMED, "LENS_OUTPUT statement must be a non-empty string")
    positions = payload["positions"]
    if (not isinstance(positions, dict) or set(positions) - set(LENS_QUESTIONS)
            or not all(p in POSITIONS for p in positions.values())):
        raise CXPError(E_MALFORMED, f"LENS_OUTPUT positions map {LENS_QUESTIONS} to {POSITIONS}")
    _short_strings(payload["uncertainties"], "uncertainties")
    _short_strings(payload["unsupported_claims"], "unsupported_claims")
    if payload["next_action"] is not None and not (isinstance(payload["next_action"], str) and payload["next_action"].strip()):
        raise CXPError(E_MALFORMED, "LENS_OUTPUT next_action must be a non-empty string or null")
    details = payload["details"]
    if not isinstance(details, dict) or len(details) > MAX_LENS_LIST_ITEMS:
        raise CXPError(E_MALFORMED, "LENS_OUTPUT details must be an object")
    for value in details.values():
        if isinstance(value, list):
            _short_strings(value, "details list")
        elif not (isinstance(value, str) and value.strip() and len(value) <= MAX_STATEMENT_CHARS):
            raise CXPError(E_MALFORMED, "LENS_OUTPUT details values must be strings or lists of strings")


def _parse_sources(raw_sources) -> tuple:
    if not isinstance(raw_sources, list):
        raise CXPError(E_MALFORMED, "sources must be a list")
    by_id = {}
    for item in raw_sources:
        if not isinstance(item, dict) or set(item) - _SOURCE_KEYS or not {"source_type", "locator"} <= set(item):
            raise CXPError(E_MALFORMED, "each source needs source_type and locator (optional independence_key)")
        source_type = _require_enum(item, "source_type", SOURCE_TYPES)
        locator = item["locator"]
        if not isinstance(locator, str) or not locator or len(locator) > MAX_LOCATOR_CHARS:
            raise CXPError(E_MALFORMED, "source locator must be a non-empty string")
        source_id = digest_id("source", {"source_type": source_type, "locator": locator})
        independence_key = _optional_str(item, "independence_key", MAX_LOCATOR_CHARS) or source_id
        if source_id in by_id:
            raise CXPError(E_MALFORMED, "duplicate source in one record")
        by_id[source_id] = SourceRef(source_id, source_type, locator, independence_key)
    return tuple(by_id[k] for k in sorted(by_id))


def _parse_derived_from(raw_parents) -> tuple:
    if not isinstance(raw_parents, list):
        raise CXPError(E_MALFORMED, "derived_from must be a list")
    for parent in raw_parents:
        if not isinstance(parent, str) or not _RECORD_ID_PATTERN.match(parent):
            raise CXPError(E_MALFORMED, "derived_from entries must be record ids")
    if len(set(raw_parents)) != len(raw_parents):
        raise CXPError(E_MALFORMED, "derived_from contains duplicates")
    return tuple(sorted(raw_parents))


def parse_event(raw) -> tuple:
    """Structural validation of one wire event -> (CognitiveRecord,
    Occurrence). Raises CXPError. Performs no lineage lookup; see
    resolve_lineage() for the checks that need already-accepted records."""
    if not isinstance(raw, dict):
        raise CXPError(E_MALFORMED, "event must be an object")
    version = _parse_schema_version(raw)  # version first: an unknown version may have an unknown shape
    unknown = set(raw) - _TOP_LEVEL_KEYS
    missing = {"kind", "representation", "evidence", "verification", "provenance", "privacy", "payload",
               "occurrence"} - set(raw)
    if unknown or missing:
        raise CXPError(E_MALFORMED, f"unknown keys {sorted(unknown)}; missing keys {sorted(missing)}")

    kind = raw.get("kind")
    if kind in RESERVED_KINDS:
        raise CXPError(E_KIND_NOT_ENABLED, f"kind {kind} is reserved and not enabled in CXP v1 slice R1")
    kind = _require_enum(raw, "kind", ENABLED_KINDS)
    representation = _require_enum(raw, "representation", REPRESENTATIONS)
    evidence = _require_enum(raw, "evidence", EVIDENCE_CLASSES)
    verification = _require_enum(raw, "verification", VERIFICATION_STATES)
    provenance = _require_enum(raw, "provenance", PROVENANCE_KINDS)
    privacy = _require_enum(raw, "privacy", PRIVACY_CLASSES)
    payload_json = _parse_payload(kind, raw["payload"])
    sources = _parse_sources(raw.get("sources", []))
    derived_from = _parse_derived_from(raw.get("derived_from", []))
    verification_ref = raw.get("verification_ref")
    if verification_ref is not None and (not isinstance(verification_ref, str) or not _RECORD_ID_PATTERN.match(verification_ref)):
        raise CXPError(E_MALFORMED, "verification_ref must be a record id or null")
    consent_ref = _optional_str(raw, "consent_ref")

    # kind rules
    if kind in _ROOT_KINDS:
        if not sources or derived_from:
            raise CXPError(E_KIND_RULE, f"{kind} must cite at least one source and derive from nothing")
    else:
        if not derived_from or sources:
            raise CXPError(E_KIND_RULE, f"{kind} must derive from at least one record and cite no sources of its own")
    if kind == KIND_OBSERVATION:
        if provenance not in (OBSERVED, HUMAN_ASSERTED, SYSTEM_ASSERTED):
            raise CXPError(E_KIND_RULE, "OBSERVATION provenance must be OBSERVED, HUMAN_ASSERTED or SYSTEM_ASSERTED")
        if representation not in (REP_QUOTATION, REP_PARAPHRASE):
            raise CXPError(E_KIND_RULE, "OBSERVATION representation must be QUOTATION or PARAPHRASE")
    elif kind == KIND_CLAIM:
        if provenance not in (DERIVED, UNVERIFIED_INTERPRETATION):
            raise CXPError(E_KIND_RULE, "CLAIM provenance must be DERIVED or UNVERIFIED_INTERPRETATION")
    elif kind == KIND_VERIFICATION_RESULT:
        if provenance not in (HUMAN_ASSERTED, AUTHORIZED_CONCLUSION):
            raise CXPError(E_KIND_RULE, "VERIFICATION_RESULT provenance must be HUMAN_ASSERTED or AUTHORIZED_CONCLUSION")
        if verification != VER_UNVERIFIED:
            raise CXPError(E_KIND_RULE, "a VERIFICATION_RESULT cannot itself claim to be verified")
    elif kind == KIND_CONTRADICTION:
        # A contradiction is an interpretation that its claims conflict. It
        # derives from exactly the claims it names (so lineage covers every
        # side) and carries no truth status of its own: resolution is
        # computed by cognition.contradiction from admissible verification,
        # never declared on the record.
        if list(derived_from) != json.loads(payload_json)["claims"]:
            raise CXPError(E_KIND_RULE, "CONTRADICTION derived_from must equal its claims")
        if provenance not in (DERIVED, UNVERIFIED_INTERPRETATION, HUMAN_ASSERTED):
            raise CXPError(E_KIND_RULE, "CONTRADICTION provenance must be DERIVED, UNVERIFIED_INTERPRETATION or HUMAN_ASSERTED")
        if representation != REP_INFERENCE:
            raise CXPError(E_KIND_RULE, "CONTRADICTION representation must be INFERENCE")
        if verification != VER_UNVERIFIED:
            raise CXPError(E_KIND_RULE, "a CONTRADICTION carries no verification status of its own")
    elif kind == KIND_LENS_OUTPUT:
        # A lens interprets; it never observes, quotes, or verifies.
        if provenance != UNVERIFIED_INTERPRETATION:
            raise CXPError(E_KIND_RULE, "LENS_OUTPUT provenance must be UNVERIFIED_INTERPRETATION")
        if representation == REP_QUOTATION:
            raise CXPError(E_KIND_RULE, "a LENS_OUTPUT cannot be a QUOTATION")
        if verification != VER_UNVERIFIED:
            raise CXPError(E_KIND_RULE, "a LENS_OUTPUT is never verified")

    # verification rules that need no lookup
    if verification in _REQUIRES_VERIFICATION_REF:
        if verification_ref is None:
            raise CXPError(E_VERIFICATION_UNSUPPORTED, f"{verification} requires a verification_ref")
        if verification == VER_VERIFIED and representation in _NEVER_VERIFIABLE_REPRESENTATIONS:
            raise CXPError(E_VERIFICATION_UNSUPPORTED, f"a {representation} can never be VERIFIED")
    elif verification_ref is not None:
        raise CXPError(E_KIND_RULE, f"verification_ref is only meaningful for {_REQUIRES_VERIFICATION_REF}")

    if privacy == PRIV_PERSONAL and consent_ref is None:
        raise CXPError(E_PRIVACY_CONSENT_REQUIRED, "PERSONAL records require a consent_ref")

    occ = raw["occurrence"]
    if not isinstance(occ, dict) or set(occ) - _OCCURRENCE_KEYS or not {"emitter_id", "observed_at"} <= set(occ):
        raise CXPError(E_MALFORMED, "occurrence needs emitter_id and observed_at (optional correlation_id, causation_id)")
    emitter_id = _validate_identifier(occ["emitter_id"], "occurrence.emitter_id")
    observed_at = occ["observed_at"]
    if not isinstance(observed_at, str) or not _TIMESTAMP_PATTERN.match(observed_at):
        raise CXPError(E_MALFORMED, "occurrence.observed_at must be an ISO-8601 timestamp with zone")
    correlation_id = _optional_str(occ, "correlation_id")
    causation_id = _optional_str(occ, "causation_id")

    content_id = digest_id("content", {"kind": kind, "representation": representation,
                                       "payload": json.loads(payload_json)})
    record = CognitiveRecord(
        schema_version=version, kind=kind, representation=representation, evidence=evidence,
        verification=verification, provenance=provenance, privacy=privacy, payload_json=payload_json,
        sources=sources, derived_from=derived_from, verification_ref=verification_ref,
        consent_ref=consent_ref, content_id=content_id, record_id="",
    )
    record_id = digest_id("record", record.identity_fields())
    record = dataclasses.replace(record, record_id=record_id)
    occurrence = Occurrence(
        occurrence_id=digest_id("occurrence", {"record_id": record_id, "emitter_id": emitter_id,
                                               "observed_at": observed_at}),
        record_id=record_id, emitter_id=emitter_id, observed_at=observed_at,
        correlation_id=correlation_id, causation_id=causation_id,
    )
    return record, occurrence


# ---------------------------------------------------------------------------
# lineage (needs already-accepted records)
# ---------------------------------------------------------------------------

def evidence_ceiling(root_sources: tuple) -> tuple:
    """The evidence classes a set of root sources can support."""
    allowed = [EV_NONE]
    independent = {s["independence_key"] for s in root_sources}
    if len(independent) >= 1:
        allowed.append(EV_SINGLE_SOURCE)
    if len(independent) >= 2:
        allowed.append(EV_INDEPENDENT_SOURCES)
    if any(s["source_type"] == SOURCE_TYPE_EXPERIMENT for s in root_sources):
        allowed.append(EV_EXPERIMENT_REFERENCE)
    return tuple(allowed)


def resolve_lineage(record: CognitiveRecord, lookup: Callable[[str], Optional[dict]]) -> tuple:
    """Lineage checks against already-accepted records. `lookup(record_id)`
    returns that record's stored metadata (with computed root_sources,
    erased flag and, for VERIFICATION_RESULTs, verification_target and
    verification_outcome), or None. Returns this record's root sources
    (sorted, de-duplicated by source_id). Raises CXPError."""
    if record.kind in _ROOT_KINDS:
        roots = {s.source_id: s.to_dict() for s in record.sources}
    else:
        roots = {}
        parents = []
        for parent_id in record.derived_from:
            parent = lookup(parent_id)
            if parent is None:
                raise CXPError(E_LINEAGE_UNRESOLVED, f"parent {parent_id} has not been accepted")
            if parent.get("erased"):
                raise CXPError(E_ERASED, f"parent {parent_id} has been erased")
            if record.kind == KIND_LENS_OUTPUT and parent.get("kind") in (KIND_LENS_OUTPUT, KIND_CONTRADICTION):
                # Recursion guard: lens output is never lens input.
                raise CXPError(E_KIND_RULE, f"a LENS_OUTPUT cannot derive from a {parent['kind']}")
            parents.append(parent)
            for source in parent["root_sources"]:
                roots[source["source_id"]] = source
        strongest = max(EVIDENCE_CLASSES.index(p["evidence"]) for p in parents)
        if EVIDENCE_CLASSES.index(record.evidence) > strongest:
            raise CXPError(E_EVIDENCE_INFLATION,
                           f"{record.evidence} exceeds the strongest parent's {EVIDENCE_CLASSES[strongest]}")
        most_restrictive = max(PRIVACY_CLASSES.index(p["privacy"]) for p in parents)
        if PRIVACY_CLASSES.index(record.privacy) < most_restrictive:
            raise CXPError(E_PRIVACY_DOWNGRADE,
                           f"{record.privacy} is less restrictive than a parent's {PRIVACY_CLASSES[most_restrictive]}")
    root_sources = tuple(roots[k] for k in sorted(roots))

    if record.evidence not in evidence_ceiling(root_sources):
        raise CXPError(E_EVIDENCE_INFLATION,
                       f"{record.evidence} is not supported by {len({s['independence_key'] for s in root_sources})} "
                       "independent root source(s)")

    if record.verification_ref is not None:
        result = lookup(record.verification_ref)
        if result is None or result.get("kind") != KIND_VERIFICATION_RESULT:
            raise CXPError(E_VERIFICATION_UNSUPPORTED, "verification_ref does not name an accepted VERIFICATION_RESULT")
        if result.get("verification_target") != record.content_id:
            raise CXPError(E_VERIFICATION_UNSUPPORTED, "verification_ref targets different content")
        if result.get("verification_outcome") != record.verification:
            raise CXPError(E_VERIFICATION_UNSUPPORTED,
                           f"verification_ref outcome {result.get('verification_outcome')} != {record.verification}")
    return root_sources
