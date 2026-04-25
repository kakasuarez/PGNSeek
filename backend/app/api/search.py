"""
app/api/search.py

Search endpoint. Two routes:
  GET /api/v1/search   — main search with query string + optional filters
  GET /api/v1/games/{game_hash}  — retrieve a single game by hash
  GET /api/v1/similar/{game_hash} — find similar games

The query string is processed by the three-stage pipeline in app/search/query.py.
"""

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
import structlog

from app.config import settings
from app.models.schemas import SearchResponse, ErrorDetail
from app.search.query import build_search_request
from app.search.executor import execute_search, get_game_by_hash, build_similarity_query

log = structlog.get_logger()
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search chess games",
    description=(
        "Search across millions of chess games using natural language. "
        "Examples: 'aggressive Sicilian white wins 2400+', "
        "'Carlsen positional endgame', 'French defense under 30 moves draw'"
    ),
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def search(
    request: Request,
    q: str = Query(
        default="",
        description="Natural language search query",
        max_length=300,
    ),
    page_size: int = Query(
        default=settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
    ),
    cursor: str | None = Query(
        default=None,
        description="Pagination cursor from previous response (opaque token)",
    ),
):
    log.info(
        "search_request", query=q, page_size=page_size, has_cursor=cursor is not None
    )

    try:
        es_request = build_search_request(q, page_size=page_size, cursor=cursor)
    except Exception as exc:
        log.warning("query_build_failed", query=q, error=str(exc))
        return JSONResponse(
            status_code=400,
            content=ErrorDetail(
                error="query_parse_error",
                message="Could not parse your query. Try simpler terms.",
                detail={"raw_query": q},
            ).model_dump(),
        )

    es = request.app.state.es
    response = await execute_search(es, es_request)

    log.info(
        "search_complete", query=q, total=response.total, returned=len(response.results)
    )
    return response


@router.get(
    "/games/{game_hash}",
    summary="Get a single game by its hash",
)
async def get_game(request: Request, game_hash: str):
    es = request.app.state.es
    game = await get_game_by_hash(es, game_hash)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.get("/games/similar/{game_hash}", summary="Get similar games from its hash")
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
def find_similar(request: Request, game_hash: str):
    es = request.app.state.es
    results = build_similarity_query(es, game_hash)
    if not results:
        raise HTTPException(status_code=404, detail="No similar games found")
    return results
