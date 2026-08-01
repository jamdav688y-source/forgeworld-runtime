"""Semantic search boundary.

This module intentionally contains no embedding model, no vector index,
and no heavy ML import. It exists only as a disabled adapter interface so
the rest of the codebase (search.py, app.py) has a stable place to check
"is semantic search available" without importing anything expensive.

Semantic search may only be enabled after FTS5 has been used in real
operation and its shortcomings have been measured (see
KNOWN_LIMITATIONS.md / VALIDATION_REPORT.md) -- not merely because
embeddings are fashionable.
"""
from __future__ import annotations

from typing import Protocol


class SemanticIndexAdapter(Protocol):
    """Interface a future semantic index would implement.

    Deliberately unimplemented in this cycle. Do not add sentence-transformers,
    torch, faiss, chromadb, or any other heavy dependency to satisfy this
    protocol without first updating KNOWN_LIMITATIONS.md with measured
    justification (see PROMPT_CONSTRUCTION / SEMANTIC_SEARCH_BOUNDARY in the
    project directive).
    """

    def is_enabled(self) -> bool:
        ...

    def index_screenshot(self, screenshot_id: int, text: str) -> None:
        ...

    def query(self, text: str, top_k: int = 10) -> list[tuple[int, float]]:
        ...


class DisabledSemanticIndexAdapter:
    """Default adapter: always disabled, does no indexing, does no querying."""

    def is_enabled(self) -> bool:
        return False

    def index_screenshot(self, screenshot_id: int, text: str) -> None:
        return None

    def query(self, text: str, top_k: int = 10) -> list[tuple[int, float]]:
        return []


def get_semantic_index_adapter() -> DisabledSemanticIndexAdapter:
    return DisabledSemanticIndexAdapter()
