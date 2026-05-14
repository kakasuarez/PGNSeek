"""
Elasticsearch-backed SearchBackend implementation.
"""

from typing import Any, Generator

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.config import settings
from app.models.schemas import SearchResponse
from app.search.backend import SearchBackend
from app.search.executor import execute_search, get_game_by_hash, build_similarity_query
from app.search.index import ALIAS_NAME, get_es_client, setup_index
from app.search.query import ESSearchRequest


class ElasticsearchSearchBackend(SearchBackend):
    def __init__(self, client: Elasticsearch | None = None) -> None:
        self.client = client or get_es_client()

    def setup(self) -> None:
        setup_index(self.client)

    def close(self) -> None:
        self.client.close()

    def health(self) -> dict[str, Any]:
        cluster = self.client.cluster.health()
        return {
            "backend": "elasticsearch",
            "backend_status": cluster["status"],
            "index": settings.ES_INDEX_ALIAS,
        }

    async def execute_search(self, req: ESSearchRequest) -> SearchResponse:
        return await execute_search(self.client, req)

    async def get_game_by_hash(self, game_hash: str) -> dict | None:
        return await get_game_by_hash(self.client, game_hash)

    def build_similarity_query(self, game_hash: str, size: int = 10) -> list:
        return build_similarity_query(self.client, game_hash, size=size)

    def bulk_index(self, documents: list[dict]) -> int:
        success, _ = bulk(
            self.client,
            self._iter_bulk_actions(documents),
            raise_on_error=False,
        )
        return success

    @staticmethod
    def _iter_bulk_actions(documents: list[dict]) -> Generator[dict, None, None]:
        for doc in documents:
            yield {
                "_index": ALIAS_NAME,
                "_id": doc["game_hash"],
                "_source": doc,
            }
