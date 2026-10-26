"""CANDIDATE RETRIEVAL stage: a provider-neutral retrieval adapter interface,
a deterministic offline mock, and a documented-but-unwired real-web hook --
same three-part shape as ocr.py's OCRProvider/FixtureOCRProvider/CloudOCRProvider,
so the two extension points are recognizable as the same pattern rather than
two different ones invented separately.

Reachability of registered retrieval connectors is checked with
`capabilities.discover.probe_one` directly -- the exact function this
repository's Capability Discovery mechanism already uses for every other
connector profile (perception/registry.json follows the identical
id/kind/provider/check/tags/cost shape as capabilities/registry.json). No
new reachability-probing logic is written here.

Acceptance test: "Every retrieved page begins as CANDIDATE_MATCH." --
enforced structurally by schema.new_candidate_source, not by this module;
this module never sets validation_status itself.
"""
import json
from pathlib import Path

from capabilities.discover import probe_one
from whatsapp.src import ledger as wa_ledger

from . import schema
from .common import now_iso

MODULE_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = MODULE_ROOT / "registry.json"


def load_registry() -> list:
    with open(REGISTRY_PATH) as f:
        return json.load(f)["capabilities"]


def probe_registry() -> dict:
    """Measured, not assumed: reuses capabilities.discover.probe_one so
    'is this retrieval connector actually reachable right now' is answered
    the same way every other capability in this repo answers it."""
    results = {}
    for conn in load_registry():
        confidence, evidence = probe_one(conn["check"])
        results[conn["id"]] = {"reachability_confidence": confidence, "evidence": evidence}
    return results


class RetrievalProvider:
    """Duck-typed interface every retrieval connector implements."""
    id = "unset"
    name = "unset"

    def search(self, query: str, entity_signal: dict) -> list:
        """Returns a list of raw candidate dicts: [{"url", "title", "snippet"}, ...]."""
        raise NotImplementedError


class FixtureRetrievalProvider(RetrievalProvider):
    """Deterministic offline mock: exact query text -> canned candidate list.
    Matches the acceptance tests' own sanction of "mocked provider
    responses" for offline tests -- named as a mock everywhere it appears.
    """
    id = "fixture_retrieval"
    name = "mock:fixture_retrieval"

    def __init__(self, fixture_map: dict):
        self._fixtures = dict(fixture_map)

    def search(self, query: str, entity_signal: dict) -> list:
        return list(self._fixtures.get(query, []))


class WebSearchProvider(RetrievalProvider):
    """Documented extension point for a real web-search/retrieval API.
    Not wired: no PERCEPTION_WEB_SEARCH_API_KEY is configured, and this
    proof stays fully offline per the mission's own constraint. Wiring
    this in later means filling in `search()` -- retrieve_candidates()
    below already works with any RetrievalProvider, this one included.
    """
    id = "web_search_unwired"
    name = "unwired:web_search"

    def search(self, query: str, entity_signal: dict) -> list:
        raise NotImplementedError(
            "WebSearchProvider is a documented extension point, not a wired provider -- "
            "no retrieval credentials are configured for this channel."
        )


def _record(stage: str, **fields) -> None:
    wa_ledger.append(wa_ledger.EXECUTION_LEDGER, {
        "system": "perception",
        "stage": stage,
        "recorded_at": now_iso(),
        **fields,
    })


def _query_for(entity_signal: dict) -> str:
    value = entity_signal.get("value") or {}
    return value.get("text", "")


def retrieve_candidates(observation: dict, entity_signals: list, provider: RetrievalProvider) -> list:
    """CANDIDATE RETRIEVAL. One retrieval call per entity signal; every
    resulting CandidateSource starts life as CANDIDATE_MATCH (enforced by
    schema.new_candidate_source, not by this function)."""
    image_id = observation["source_image_id"]
    image_sha256 = observation["source_image_sha256"]
    candidates = []

    for entity_signal in entity_signals:
        query = _query_for(entity_signal)
        if not query:
            continue

        raw_results = provider.search(query, entity_signal)
        _record(
            "CANDIDATE_RETRIEVAL", image_sha256=image_sha256, observation_id=observation["id"],
            entity_signal_id=entity_signal["id"], provider=provider.name, query=query,
            result_count=len(raw_results), state="RAN",
        )

        for raw in raw_results:
            candidate = schema.new_candidate_source(
                image_id=image_id, image_sha256=image_sha256, provider=provider.name,
                url=raw["url"], title=raw.get("title", ""), snippet=raw.get("snippet", ""),
                retrieval_confidence=raw.get("confidence", 0.5),
                query_signal_ids=[entity_signal["id"]], raw_response=raw,
            )
            errors = schema.validate_candidate_source(candidate)
            if errors:
                raise ValueError(f"CandidateSource failed validation: {errors}")
            assert candidate["validation_status"] == schema.CANDIDATE_MATCH

            _record(
                "CANDIDATE_RETRIEVAL", image_sha256=image_sha256, observation_id=observation["id"],
                candidate_id=candidate["id"], url=candidate["url"],
                state="CANDIDATE_MATCH",
            )
            candidates.append(candidate)

    return candidates
