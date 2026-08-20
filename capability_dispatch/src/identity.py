"""CANDIDATE IDENTITY RESOLUTION -- provider-neutral interface.

Same three-part shape as perception/src/ocr.py's OCRProvider /
FixtureOCRProvider / CloudOCRProvider, applied to a new domain: an
IdentityResolver interface, a deterministic offline mock
(FixtureIdentityResolver, the only one actually exercised in this proof),
and a documented-but-unwired real-lookup hook
(UnwiredRegistryIdentityResolver). No installation, cloning, or execution
happens anywhere in this module to determine identity -- resolvers only
ever read a fixture map or (when wired, later) query a read-only metadata
API.

Structural guarantee, independent of which resolver is used: a candidate
whose canonical_hint is a known link-shortener domain can never resolve to
VERIFIED. This is enforced in resolve_identity() itself, not left to
resolver implementations to remember -- "Do not resolve shortened social
URLs by inference" is a hard mission constraint, not a best-effort one.
"""
from urllib.parse import urlparse

from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso

KNOWN_URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly", "is.gd", "rebrand.ly",
}


class IdentityResolver:
    """Duck-typed interface every identity resolver implements."""
    name = "unset"

    def resolve(self, candidate: dict) -> dict:
        """Returns a raw response dict: {"resolution", "canonical_repository_url",
        "canonical_owner", "license_id", "evidence_basis", "confidence"}."""
        raise NotImplementedError


class FixtureIdentityResolver(IdentityResolver):
    """Deterministic offline mock: normalized_name -> canned resolution.
    Named as a mock everywhere it appears, matching perception/src/ocr.py's
    FixtureOCRProvider convention -- never mistakable for a real registry
    lookup."""
    name = "mock:fixture_identity"

    def __init__(self, fixture_map: dict):
        self._fixtures = dict(fixture_map)

    def resolve(self, candidate: dict) -> dict:
        entry = self._fixtures.get(candidate["normalized_name"])
        if entry is None:
            return {
                "resolution": "UNAVAILABLE", "canonical_repository_url": None,
                "canonical_owner": None, "license_id": None,
                "evidence_basis": "no fixture entry registered for this candidate", "confidence": 0.0,
            }
        return entry


class UnwiredRegistryIdentityResolver(IdentityResolver):
    """Documented extension point for a real identity lookup (e.g. GitHub
    API repo/owner/license/archived-status query, package-registry
    metadata). Not wired: no credentials are configured for any such
    service in this environment, and this proof stays fully offline per
    the mission's own constraint. Wiring this in later means filling in
    `resolve()` with a *read-only* metadata query -- never a clone,
    install, or execution -- the rest of this module already works with
    any IdentityResolver, this one included, unchanged.
    """
    name = "unwired:registry_lookup"

    def resolve(self, candidate: dict) -> dict:
        raise NotImplementedError(
            "UnwiredRegistryIdentityResolver is a documented extension point, not a wired "
            "resolver -- no identity/registry-lookup credentials are configured for this channel."
        )


def _is_shortened_url(url) -> bool:
    if not url:
        return False
    try:
        domain = urlparse(url).netloc.lower()
    except (ValueError, AttributeError):
        return False
    return domain in KNOWN_URL_SHORTENERS


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "capability_dispatch",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def resolve_identity(artifact_id: str, artifact_sha256: str, candidate: dict, resolver: IdentityResolver) -> dict:
    """Runs identity resolution for one candidate. Returns a validated
    IdentityEvidence object; never mutates `candidate` in place -- callers
    apply the evidence explicitly via apply_identity_evidence(), so
    "evidence was produced" and "candidate state was updated" are always
    two separate, auditable steps."""
    raw = resolver.resolve(candidate)

    resolution = raw["resolution"]
    basis = raw["evidence_basis"]

    if _is_shortened_url(candidate.get("canonical_hint")) and resolution == "VERIFIED":
        # Structural override: no resolver, however confident, may turn a
        # shortened link into a verified identity by inference.
        resolution = "AMBIGUOUS"
        basis = (
            f"{basis} -- OVERRIDDEN: canonical_hint is a known link-shortener domain; "
            f"a shortened link can never resolve to VERIFIED without independently "
            f"following it, which this mission does not do"
        )

    _record(
        "IDENTITY_RESOLUTION", artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
        resolver=resolver.name, resolution=resolution, state="RAN",
    )

    evidence = schema.new_identity_evidence(
        artifact_id=artifact_id, artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
        resolver_provider=resolver.name, resolution=resolution,
        canonical_repository_url=raw.get("canonical_repository_url"),
        canonical_owner=raw.get("canonical_owner"), license_id=raw.get("license_id"),
        evidence_basis=basis, confidence=raw.get("confidence", 0.0), raw_response=raw,
    )
    errors = schema.validate_identity_evidence(evidence)
    if errors:
        raise ValueError(f"IdentityEvidence failed validation: {errors}")

    _record(
        "IDENTITY_RESOLUTION", artifact_sha256=artifact_sha256, candidate_id=candidate["id"],
        evidence_id=evidence["id"], state="EVIDENCE_RECORDED",
    )
    return evidence


def apply_identity_evidence(candidate: dict, evidence: dict) -> dict:
    """Returns a NEW candidate dict with identity fields updated from
    `evidence` -- the only place a CapabilityCandidate's identity_status
    is ever allowed to change from UNVERIFIED."""
    if evidence["candidate_id"] != candidate["id"]:
        raise ValueError("evidence does not reference this candidate")
    updated = dict(candidate)
    updated["identity_status"] = evidence["resolution"]
    updated["canonical_repository_url"] = evidence["canonical_repository_url"]
    updated["maintainer_identity"] = evidence["canonical_owner"]
    updated["identity_verified_at"] = evidence["created_at"]
    return updated
