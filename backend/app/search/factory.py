"""
Search backend factory.
"""

from app.config import settings
from app.search.backend import SearchBackend


def create_search_backend() -> SearchBackend:
    if settings.SEARCH_BACKEND == "meilisearch":
        from app.search.meilisearch_backend import MeilisearchSearchBackend

        return MeilisearchSearchBackend()
    from app.search.elasticsearch_backend import ElasticsearchSearchBackend

    return ElasticsearchSearchBackend()
