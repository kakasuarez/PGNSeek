"""
Search backend interface.

The API and ingestion pipeline depend on this protocol instead of a concrete
search engine. Elasticsearch is still the active implementation; Meilisearch
can be added by implementing this same contract.
"""

from typing import Protocol, Any

from app.models.schemas import SearchResponse
from app.search.query import ESSearchRequest


class SearchBackend(Protocol):
    def setup(self) -> None:
        """Create indexes/settings needed by the backend."""
        ...

    def close(self) -> None:
        """Release backend resources."""
        ...

    def health(self) -> dict[str, Any]:
        """Return backend-specific health details."""
        ...

    async def execute_search(self, req: ESSearchRequest) -> SearchResponse:
        """Run a prepared search request."""
        ...

    async def get_game_by_hash(self, game_hash: str) -> dict | None:
        """Fetch one game document by its stable hash."""
        ...

    def build_similarity_query(self, game_hash: str, size: int = 10) -> list[dict]:
        """Return games similar to the given game hash."""
        ...

    def bulk_index(self, documents: list[dict]) -> int:
        """Index a batch of documents and return the success count."""
        ...
