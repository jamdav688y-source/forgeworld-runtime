"""ForgeWorld ecosystem integration boundary.

Mirrors the pattern established in embeddings.py: each integration is a
`Protocol` describing the shape a future adapter would implement, plus a
disabled no-op default. Nothing in this module imports a network client,
SDK, or heavy dependency, and nothing elsewhere in the app depends on
these adapters doing anything -- the application is fully functional with
every integration disabled, which is also the default and current state.

These are extension points, not implementations. Wiring a real adapter in
is future, explicitly-authorized work; this module only reserves the
shape so that work doesn't require touching indexer.py/app.py/database.py
when it happens.

Integrations reserved for a later cycle:
  - Cinema Engine          -- hand off CREATE_CINEMA_BRIEF prompt packets
  - Repository Intelligence -- surface source-grounded code/repo context
  - Executive Bootstrap     -- feed institutional-memory summaries upward
  - Knowledge Graph         -- publish entities/tags as graph edges
"""
from __future__ import annotations

from typing import Any, Protocol


class ForgeWorldIntegrationAdapter(Protocol):
    """Common shape every ForgeWorld integration adapter implements."""

    def is_enabled(self) -> bool:
        ...

    def describe(self) -> dict[str, Any]:
        """Return a small JSON-safe status dict for /api/system_status."""
        ...


class _DisabledAdapter:
    """Shared no-op base: every method is inert until a real adapter
    replaces it. Never raises, never calls out, never touches the DB."""

    name = "unconfigured"

    def is_enabled(self) -> bool:
        return False

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "enabled": False, "status": "not configured"}


class CinemaEngineAdapter(_DisabledAdapter):
    """Future extension point: hand off CREATE_CINEMA_BRIEF prompt
    packets (see prompts.py) to a ForgeWorld Cinema Engine for shot-list
    or storyboard generation. Disabled by default."""

    name = "cinema_engine"

    def send_brief(self, brief_markdown: str) -> None:
        raise NotImplementedError("Cinema Engine integration is not enabled in this cycle")


class RepositoryIntelligenceAdapter(_DisabledAdapter):
    """Future extension point: let a ForgeWorld Repository Intelligence
    service pull source-grounded context (OCR'd code screenshots, terminal
    captures) discovered by this app. Disabled by default."""

    name = "repository_intelligence"

    def query(self, question: str) -> list[dict[str, Any]]:
        raise NotImplementedError("Repository Intelligence integration is not enabled in this cycle")


class ExecutiveBootstrapAdapter(_DisabledAdapter):
    """Future extension point: push SYSTEM_EXTRACTIVE_SUMMARY content and
    operator notes upward into a ForgeWorld Executive Bootstrap layer as
    institutional-memory candidates. Disabled by default."""

    name = "executive_bootstrap"

    def submit_memory_candidate(self, screenshot_id: int, summary: str) -> None:
        raise NotImplementedError("Executive Bootstrap integration is not enabled in this cycle")


class KnowledgeGraphAdapter(_DisabledAdapter):
    """Future extension point: publish tags/entities (see
    indexer.classify_text) as nodes/edges in a ForgeWorld Knowledge Graph.
    Disabled by default."""

    name = "knowledge_graph"

    def publish_entity(self, name: str, entity_type: str, related_to: list[str]) -> None:
        raise NotImplementedError("Knowledge Graph integration is not enabled in this cycle")


def get_integration_adapters() -> dict[str, ForgeWorldIntegrationAdapter]:
    """Every registered ForgeWorld integration adapter, all disabled by
    default. Callers (e.g. /api/system_status) can report on these without
    the app depending on any of them being real."""
    return {
        "cinema_engine": CinemaEngineAdapter(),
        "repository_intelligence": RepositoryIntelligenceAdapter(),
        "executive_bootstrap": ExecutiveBootstrapAdapter(),
        "knowledge_graph": KnowledgeGraphAdapter(),
    }
