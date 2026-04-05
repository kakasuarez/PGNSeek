"""
app/search/executor.py

Executes a pre-built ESSearchRequest against Elasticsearch.
Handles: pagination cursors, response shaping, aggregation mapping.

Pagination strategy: search_after (NOT from/size).
  - from/size fails beyond ES_MAX_RESULT_WINDOW (default 10,000)
  - search_after is cursor-based, stateless, and works at any depth
  - Cursor is base64-encoded JSON of the last hit's sort values
"""

import json
import base64
from elasticsearch import Elasticsearch, NotFoundError
import structlog

from app.config import settings
from app.search.query import ESSearchRequest
from app.models.schemas import (
    SearchResponse, GameResult, Aggregations,
    BucketCount, QueryDebug,
)

log = structlog.get_logger()


def _encode_cursor(sort_values: list) -> str:
    return base64.urlsafe_b64encode(json.dumps(sort_values).encode()).decode()


def _decode_cursor(cursor: str) -> list:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())


async def execute_search(es: Elasticsearch, req: ESSearchRequest) -> SearchResponse:
    body: dict = {
        "query":   req.query,
        "sort":    req.sort,
        "size":    req.size,
        "_source": req.source_fields,
    }

    if req.aggs:
        body["aggs"] = req.aggs

    if req.search_after:
        body["search_after"] = req.search_after

    try:
        resp = es.search(index=settings.ES_INDEX_ALIAS, body=body)
    except Exception as exc:
        log.error("es_search_failed", error=str(exc))
        raise

    hits = resp["hits"]["hits"]
    total = resp["hits"]["total"]["value"]

    results = [GameResult(**hit["_source"]) for hit in hits]

    # Cursor is the sort values of the last hit
    next_cursor = None
    if hits and len(hits) == req.size:
        next_cursor = _encode_cursor(hits[-1]["sort"])

    # Aggregations
    raw_aggs = resp.get("aggregations", {})
    aggs = Aggregations(
        openings=_buckets(raw_aggs, "openings"),
        results=_buckets(raw_aggs, "results"),
        years=_buckets(raw_aggs, "years"),
        eco_categories=_buckets(raw_aggs, "eco_categories"),
    )

    debug = QueryDebug(
        raw_query=req.debug_tokens.get("raw_query", ""),
        detected_tokens=req.debug_tokens,
        must_clauses=req.debug_must,
        filter_clauses=req.debug_filter,
        should_clauses=req.debug_should,
    )

    return SearchResponse(
        results=results,
        total=total,
        page_size=req.size,
        cursor=next_cursor,
        query_debug=debug,
        aggregations=aggs,
    )


async def get_game_by_hash(es: Elasticsearch, game_hash: str) -> dict | None:
    try:
        doc = es.get(index=settings.ES_INDEX_ALIAS, id=game_hash)
        return doc["_source"]
    except NotFoundError:
        return None


def _buckets(raw_aggs: dict, key: str) -> list[BucketCount]:
    if key not in raw_aggs:
        return []
    return [
        BucketCount(key=str(b["key"]), count=b["doc_count"])
        for b in raw_aggs[key].get("buckets", [])
    ]
