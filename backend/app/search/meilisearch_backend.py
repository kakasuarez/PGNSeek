"""
Meilisearch-backed SearchBackend implementation.
"""

import base64
import json
from typing import Any

import meilisearch
import structlog
from meilisearch.errors import MeilisearchApiError

from app.config import settings
from app.models.schemas import (
    Aggregations,
    BucketCount,
    GameResult,
    QueryDebug,
    SearchResponse,
)
from app.search.backend import SearchBackend
from app.search.query import ESSearchRequest

log = structlog.get_logger()

DISPLAYED_ATTRIBUTES = [
    "game_hash",
    "white",
    "black",
    "white_elo",
    "black_elo",
    "avg_rating",
    "result",
    "date",
    "year",
    "eco",
    "eco_prefix",
    "opening_name",
    "num_moves",
    "avg_material_swings",
    "max_material_swing",
    "piece_sacrifices",
    "entered_endgame",
    "endgame_move",
    "endgame_type",
    "pawn_structure_changes",
    "event",
    "site",
    "source_file",
    "pgn_moves",
]

FILTERABLE_ATTRIBUTES = [
    "result",
    "year",
    "eco",
    "eco_prefix",
    "opening_name",
    "avg_rating",
    "num_moves",
    "avg_material_swings",
    "piece_sacrifices",
    "entered_endgame",
    "endgame_type",
    "game_hash",
]

SORTABLE_ATTRIBUTES = [
    "avg_rating",
    "game_hash",
    "year",
    "avg_material_swings",
    "piece_sacrifices",
]

SEARCHABLE_ATTRIBUTES = [
    "opening_name",
    "white",
    "black",
    "event",
]

OPENING_SYNONYMS = {
    "kid": ["king's indian", "kings indian"],
    "king's indian": ["kid", "kings indian"],
    "kings indian": ["kid", "king's indian"],
    "qgd": ["queen's gambit declined"],
    "qga": ["queen's gambit accepted"],
    "rl": ["ruy lopez", "spanish game"],
    "ruy lopez": ["rl", "spanish game"],
    "nimzo": ["nimzo-indian", "nimzo indian"],
}


class MeilisearchSearchBackend(SearchBackend):
    def __init__(self) -> None:
        api_key = settings.MEILI_MASTER_KEY or None
        self.client = meilisearch.Client(settings.MEILI_HOST, api_key)
        self.index = self.client.index(settings.MEILI_INDEX)

    def setup(self) -> None:
        self._ensure_index()
        task = self.index.update_settings(
            {
                "displayedAttributes": DISPLAYED_ATTRIBUTES,
                "searchableAttributes": SEARCHABLE_ATTRIBUTES,
                "filterableAttributes": FILTERABLE_ATTRIBUTES,
                "sortableAttributes": SORTABLE_ATTRIBUTES,
                "synonyms": OPENING_SYNONYMS,
                "faceting": {"maxValuesPerFacet": 100},
                "pagination": {
                    "maxTotalHits": settings.MEILI_PAGINATION_MAX_TOTAL_HITS
                },
                "embedders": {
                    settings.MEILI_EMBEDDER: {
                        "source": "userProvided",
                        "dimensions": 19,
                    }
                },
            }
        )
        self._wait_for_task(task)

    def close(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        health = self.client.health()
        return {
            "backend": "meilisearch",
            "backend_status": health.get("status", "unknown"),
            "index": settings.MEILI_INDEX,
        }

    async def execute_search(self, req: ESSearchRequest) -> SearchResponse:
        params = self._build_search_params(req)
        search_query = params["q"]
        search_params = {key: value for key, value in params.items() if key != "q"}
        try:
            resp = self.index.search(search_query, search_params)
        except Exception as exc:
            log.error("meili_search_failed", error=str(exc))
            raise

        hits = resp.get("hits", [])
        results = [GameResult(**self._strip_internal_fields(hit)) for hit in hits]
        offset = int(resp.get("offset", params.get("offset", 0)))
        limit = int(resp.get("limit", req.size))
        total = int(resp.get("estimatedTotalHits", resp.get("totalHits", 0)))

        next_cursor = None
        if hits and offset + limit < min(total, settings.MEILI_PAGINATION_MAX_TOTAL_HITS):
            next_cursor = _encode_cursor({"offset": offset + limit})

        raw_facets = resp.get("facetDistribution", {})
        aggs = Aggregations(
            openings=_facet_buckets(raw_facets, "opening_name", 10),
            results=_facet_buckets(raw_facets, "result", 3),
            years=_facet_buckets(raw_facets, "year", 10, sort_desc=True),
            eco_categories=_facet_buckets(raw_facets, "eco_prefix", 5),
        )

        debug = QueryDebug(
            raw_query=req.debug_tokens.get("raw_query", ""),
            detected_tokens={
                **req.debug_tokens,
                "meilisearch_request": params,
            },
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

    async def get_game_by_hash(self, game_hash: str) -> dict | None:
        try:
            doc = self.index.get_document(game_hash)
        except MeilisearchApiError:
            return None
        return self._strip_internal_fields(dict(doc))

    def build_similarity_query(self, game_hash: str, size: int = 10) -> list[dict]:
        try:
            resp = self.index.get_similar_documents(
                {
                    "id": game_hash,
                    "embedder": settings.MEILI_EMBEDDER,
                    "limit": size + 1,
                    "attributesToRetrieve": DISPLAYED_ATTRIBUTES,
                }
            )
        except MeilisearchApiError:
            return []
        hits = [
            self._strip_internal_fields(hit)
            for hit in resp.get("hits", [])
            if hit.get("game_hash") != game_hash
        ]
        return hits[:size]

    def bulk_index(self, documents: list[dict]) -> int:
        if not documents:
            return 0
        meili_documents = [self._to_meili_document(doc) for doc in documents]
        task = self.index.add_documents(meili_documents, primary_key="game_hash")
        self._wait_for_task(task)
        return len(meili_documents)

    def _ensure_index(self) -> None:
        try:
            task = self.client.create_index(
                settings.MEILI_INDEX,
                {"primaryKey": "game_hash"},
            )
            self._wait_for_task(task)
        except MeilisearchApiError as exc:
            if getattr(exc, "code", "") != "index_already_exists":
                raise

    def _wait_for_task(self, task: Any) -> None:
        self.client.wait_for_task(
            task.task_uid,
            timeout_in_ms=settings.MEILI_TASK_TIMEOUT_MS,
        )

    def _build_search_params(self, req: ESSearchRequest) -> dict[str, Any]:
        tokens = _merged_tokens(req)
        text_query, attributes_to_search_on = _text_query(tokens)
        filters = _filters(tokens)
        sort = _sort(tokens)
        offset = _cursor_offset(req.search_after)

        params: dict[str, Any] = {
            "q": text_query,
            "limit": req.size,
            "offset": offset,
            "filter": filters,
            "sort": sort,
            "facets": ["opening_name", "result", "year", "eco_prefix"],
            "attributesToRetrieve": req.source_fields,
        }
        if attributes_to_search_on:
            params["attributesToSearchOn"] = attributes_to_search_on
        return params

    def _to_meili_document(self, doc: dict) -> dict:
        output = dict(doc)
        feature_vector = output.pop("feature_vector", None)
        if feature_vector:
            output["_vectors"] = {settings.MEILI_EMBEDDER: feature_vector}
        return output

    @staticmethod
    def _strip_internal_fields(doc: dict) -> dict:
        doc.pop("_vectors", None)
        return doc


def _merged_tokens(req: ESSearchRequest) -> dict[str, Any]:
    pattern_tokens = req.debug_tokens.get("pattern_tokens", {})
    keyword_tokens = req.debug_tokens.get("keyword_tokens", {})
    return {**pattern_tokens, **keyword_tokens}


def _text_query(tokens: dict[str, Any]) -> tuple[str, list[str] | None]:
    parts = []
    attributes = []

    if "opening" in tokens:
        parts.append(tokens["opening"])
        attributes.append("opening_name")

    player_result = tokens.get("player_result")
    if player_result:
        parts.append(player_result["player"])
        color = player_result.get("color")
        if color:
            attributes.append(color)
        else:
            attributes.extend(["white", "black"])

    return " ".join(parts), attributes or None


def _filters(tokens: dict[str, Any]) -> list[str]:
    filters = []

    result_map = {
        "result_white": "1-0",
        "result_black": "0-1",
        "result_draw": "1/2-1/2",
    }
    for token, result in result_map.items():
        if token in tokens:
            filters.append(f'result = "{result}"')

    if "rating_min" in tokens:
        filters.append(f"avg_rating >= {int(tokens['rating_min'][0])}")
    if "rating_range" in tokens:
        lo, hi = tokens["rating_range"]
        filters.append(f"avg_rating >= {int(lo)}")
        filters.append(f"avg_rating <= {int(hi)}")
    if "moves_max" in tokens:
        filters.append(f"num_moves <= {int(tokens['moves_max'][0])}")

    player_result = tokens.get("player_result")
    if player_result:
        outcome = player_result["outcome"]
        color = player_result.get("color")
        result_for = {
            "win": {"white": "1-0", "black": "0-1"},
            "loss": {"white": "0-1", "black": "1-0"},
            "draw": {"white": "1/2-1/2", "black": "1/2-1/2"},
        }
        if color:
            filters.append(f'result = "{result_for[outcome][color]}"')
        else:
            white_result = result_for[outcome]["white"]
            black_result = result_for[outcome]["black"]
            filters.append(
                f'(result = "{white_result}" OR result = "{black_result}")'
            )

    return filters


def _sort(tokens: dict[str, Any]) -> list[str]:
    styles = tokens.get("styles", [])
    if "aggressive" in styles:
        return ["avg_material_swings:desc", "avg_rating:desc", "game_hash:asc"]
    if "positional" in styles:
        return ["avg_material_swings:asc", "avg_rating:desc", "game_hash:asc"]
    if "sacrifices" in styles:
        return ["piece_sacrifices:desc", "avg_rating:desc", "game_hash:asc"]
    return ["avg_rating:desc", "game_hash:asc"]


def _cursor_offset(cursor_payload: Any) -> int:
    if isinstance(cursor_payload, dict):
        return int(cursor_payload.get("offset", 0))
    return 0


def _encode_cursor(payload: dict[str, int]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _facet_buckets(
    raw_facets: dict,
    key: str,
    size: int,
    sort_desc: bool = False,
) -> list[BucketCount]:
    values = raw_facets.get(key, {})
    items = list(values.items())
    if sort_desc:
        items.sort(key=lambda item: str(item[0]), reverse=True)
    else:
        items.sort(key=lambda item: item[1], reverse=True)
    return [BucketCount(key=str(value), count=count) for value, count in items[:size]]
