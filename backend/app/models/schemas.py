"""
app/models/schemas.py

Pydantic models for API request/response shapes.
These are the contract. Do not change field names without versioning the API.
"""

from pydantic import BaseModel, Field
from typing import Optional, Any


# ── Game document (what comes back from ES _source) ──────────────────────────

class GameResult(BaseModel):
    game_hash:              str
    white:                  str
    black:                  str
    white_elo:              Optional[int]   = None
    black_elo:              Optional[int]   = None
    avg_rating:             Optional[float] = None
    result:                 Optional[str]   = None   # "1-0" | "0-1" | "1/2-1/2"
    date:                   Optional[str]   = None
    year:                   Optional[int]   = None
    eco:                    Optional[str]   = None
    opening_name:           Optional[str]   = None
    num_moves:              Optional[int]   = None
    avg_material_swings:    Optional[float] = None
    piece_sacrifices:       Optional[int]   = None
    entered_endgame:        Optional[bool]  = None
    event:                  Optional[str]   = None
    source_file:            Optional[str]   = None


# ── Aggregations ─────────────────────────────────────────────────────────────

class BucketCount(BaseModel):
    key:   str
    count: int

class Aggregations(BaseModel):
    openings: list[BucketCount] = []
    results:  list[BucketCount] = []
    years:    list[BucketCount] = []
    eco_categories: list[BucketCount] = []


# ── Query debug (what the parser produced — visible in response) ─────────────

class QueryDebug(BaseModel):
    raw_query:      str
    detected_tokens: dict[str, Any] = {}
    must_clauses:   list[dict]      = []
    filter_clauses: list[dict]      = []
    should_clauses: list[dict]      = []


# ── Search response envelope ─────────────────────────────────────────────────

class SearchResponse(BaseModel):
    results:      list[GameResult]
    total:        int
    page_size:    int
    cursor:       Optional[str]   = None   # opaque search_after token (base64)
    query_debug:  QueryDebug
    aggregations: Aggregations


# ── Error envelope ───────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    error:   str                    # machine-readable code e.g. "query_parse_error"
    message: str                    # human-readable explanation
    detail:  Optional[dict] = None  # extra context (raw query, field name, etc.)
