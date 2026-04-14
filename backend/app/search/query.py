"""
app/search/query.py

Three-stage query pipeline:
  Stage 1 — Token classifier  (regex + keyword dicts)
  Stage 2 — Intent resolver   (tokens → ES clause types)
  Stage 3 — Query builder     (assemble ES bool query)

This file will be fully implemented in the next session.
Stub is here to keep imports working during scaffolding.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ESSearchRequest:
    """Everything needed to execute one ES search."""
    query:        dict[str, Any]
    aggs:         dict[str, Any]
    sort:         list[dict]
    search_after: list | None
    size:         int
    source_fields: list[str]
    debug_tokens: dict[str, Any]
    debug_must:   list[dict] = field(default_factory=list)
    debug_filter: list[dict] = field(default_factory=list)
    debug_should: list[dict] = field(default_factory=list)


def build_search_request(
    query_string: str,
    page_size: int = 20,
    cursor: str | None = None,
) -> ESSearchRequest:
    """
    Entry point for the query pipeline.
    Returns a fully-formed ESSearchRequest ready for execute_search().

    TODO: Implement Stage 1, 2, 3 in next session.
    """
    # Stub: match_all until pipeline is implemented
    return ESSearchRequest(
        query={"match_all": {}},
        aggs={},
        sort=[{"avg_rating": "desc"}, {"game_hash": "asc"}],
        search_after=None,
        size=page_size,
        source_fields=[
            "game_hash", "white", "black", "white_elo", "black_elo",
            "avg_rating", "result", "date", "year", "eco", "opening_name",
            "num_moves", "avg_material_swings", "piece_sacrifices",
            "entered_endgame", "event",
        ],
        debug_tokens={"raw_query": query_string, "note": "pipeline_stub"},
    )
