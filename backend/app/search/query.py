"""
app/search/query.py

Three-stage query pipeline:
    Stage 1 — Token classifier  (regex + keyword dicts)
    Stage 2 — Intent resolver   (tokens → ES clause types)
    Stage 3 — Query builder     (assemble ES bool query)
"""

from dataclasses import dataclass, field
from typing import Any
import re
import json, base64

PATTERNS = {
    "rating_min": r"\b(\d{4})\+",
    "rating_range": r"\b(\d{4})-(\d{4})\b",
    "result_white": r"\bwhite\s+wins?\b",
    "result_black": r"\bblack\s+wins?\b",
    "result_draw": r"\bdraw(s|n)?\b",
    # "year"
    "moves_max": r"\bunder\s+(\d+)\s+moves?\b",
}

PLAYER_RESULT_PATTERN = re.compile(
    r"\b(?P<name>[A-Za-z][a-zA-Z]*(?:\s[A-Z][a-zA-Z]*)?)\s+"
    r"(?P<outcome>wins?|won|loses?|lost|draws?|drew)"
    r"(?:\s+as\s+(?P<color>white|black))?",
    re.IGNORECASE,
)
COLOR_EXCLUDED = {"white", "black"}


def _normalise_outcome(word: str) -> str:
    w = word.lower()
    if w in {"wins", "win", "won"}:
        return "win"
    if w in {"loses", "lose", "lost"}:
        return "loss"
    return "draw"


def extract_player_result(query: str) -> dict | None:
    m = PLAYER_RESULT_PATTERN.search(query)
    if not m:
        return None
    name = m.group("name").strip()
    if name.lower() in COLOR_EXCLUDED:
        return None
    return {
        "player": name,
        "outcome": _normalise_outcome(m.group("outcome")),
        "color": (m.group("color") or "").lower() or None,
    }


def extract_patterns(query: str) -> dict:
    tokens = {}
    q = query.lower()
    for key, pattern in PATTERNS.items():
        mat = re.search(pattern, q)
        if mat:
            tokens[key] = mat.groups() if mat.lastindex else True
    return tokens


OPENINGS = {
    "sicilian": ["sicilian", "sicilian defence", "sicilian defense"],
    "kings indian": ["king's indian", "kings indian", "kid"],
    "french": ["french", "french defense", "french defence"],
    "ruy lopez": ["ruy lopez", "spanish", "spanish game"],
    "queens gambit": ["queen's gambit", "queens gambit", "qgd", "qga"],
    "caro kann": ["caro-kann", "caro kann"],
    "nimzo indian": ["nimzo", "nimzo-indian", "nimzo indian"],
    # TODO: extend these labels
}

STYLES = {
    "aggressive": ["aggressive", "attacking", "sharp", "tactical", "gambits"],
    "positional": ["positional", "strategic", "quiet", "solid", "slow"],
    "endgame": ["endgame", "end game", "ending", "technical"],
    "sacrifices": ["sacrifice", "sac", "piece sacrifice"],
}


def extract_keywords(query: str) -> dict:
    tokens = {}
    q = query.lower()
    for opening, aliases in OPENINGS.items():
        if any(alias in q for alias in aliases):
            tokens["opening"] = opening
            break
    for style, aliases in STYLES.items():
        if any(alias in q for alias in aliases):
            tokens.setdefault("styles", []).append(style)
    pr = extract_player_result(query)  # use original case, not q
    if pr:
        tokens["player_result"] = pr
    return tokens


def resolve_intent(tokens: dict) -> dict:
    must = []
    should = []
    filters = []
    must_not = []

    if "opening" in tokens:
        must.append(
            {
                "match": {
                    "opening_name": {"query": tokens["opening"], "fuzziness": "AUTO"}
                }
            }
        )

    style_field_map = {
        "aggressive": ("avg_material_swings", 3.0),
        "positional": ("avg_material_swings", 0.5),  # low swings = positional
        "endgame": ("entered_endgame", True),
    }

    for style in tokens.get("styles", []):
        if style == "aggressive":
            should.append({"range": {"avg_material_swings": {"gte": 3.0}}})
        elif style == "positional":
            should.append({"range": {"avg_material_swings": {"lte": 1.0}}})
        elif style == "endgame":
            should.append({"term": {"entered_endgame": True}})
        elif style == "sacrifices":
            should.append({"range": {"piece_sacrifices": {"gte": 1}}})

    result_map = {
        "result_white": "1-0",
        "result_black": "0-1",
        "result_draw": "1/2-1/2",
    }
    for key, val in result_map.items():
        if key in tokens:
            filters.append({"term": {"result": val}})

    if "rating_min" in tokens:
        filters.append({"range": {"avg_rating": {"gte": int(tokens["rating_min"][0])}}})
    if "rating_range" in tokens:
        lo, hi = tokens["rating_range"]
        filters.append({"range": {"avg_rating": {"gte": int(lo), "lte": int(hi)}}})
    if "moves_max" in tokens:
        max_moves = int(tokens["moves_max"][0])
        filters.append({"range": {"num_moves": {"lte": max_moves}}})

    # if "year" in tokens:
    # filters.append({"term": {"year": int(tokens["year"][0])}})
    if "player_result" in tokens:
        pr = tokens["player_result"]
        player = pr["player"]
        outcome = pr["outcome"]
        color = pr["color"]  # "white" | "black" | None

        RESULT_FOR = {
            "win": {"white": "1-0", "black": "0-1"},
            "loss": {"white": "0-1", "black": "1-0"},
            "draw": {"white": "1/2-1/2", "black": "1/2-1/2"},
        }

        if color:
            result_val = RESULT_FOR[outcome][color]
            must.append({"match": {color: {"query": player, "fuzziness": "AUTO"}}})
            filters.append({"term": {"result": result_val}})
        else:
            white_result = RESULT_FOR[outcome]["white"]
            black_result = RESULT_FOR[outcome]["black"]
            must.append(
                {
                    "bool": {
                        "minimum_should_match": 1,
                        "should": [
                            {
                                "bool": {
                                    "must": [
                                        {
                                            "match": {
                                                "white": {
                                                    "query": player,
                                                    "fuzziness": "AUTO",
                                                }
                                            }
                                        },
                                        {"term": {"result": white_result}},
                                    ]
                                }
                            },
                            {
                                "bool": {
                                    "must": [
                                        {
                                            "match": {
                                                "black": {
                                                    "query": player,
                                                    "fuzziness": "AUTO",
                                                }
                                            }
                                        },
                                        {"term": {"result": black_result}},
                                    ]
                                }
                            },
                        ],
                    }
                }
            )

    return {"must": must, "should": should, "filter": filters, "must_not": must_not}


@dataclass
class SearchRequest:
    """Everything needed to execute one Mongo search."""

    query: dict[str, Any]
    sort: list[dict]
    search_after: str | None
    size: int
    source_fields: list[str]
    debug_tokens: dict[str, Any]
    debug_must: list[dict] = field(default_factory=list)
    debug_filter: list[dict] = field(default_factory=list)
    debug_should: list[dict] = field(default_factory=list)


def build_search_request(
    query_string: str,
    page_size: int = 20,
    cursor: str | None = None,
) -> SearchRequest:
    """
    Entry point for the query pipeline.
    Returns a fully-formed SearchRequest ready for execute_search().
    """
    pattern_tokens = extract_patterns(query_string)
    keyword_tokens = extract_keywords(query_string)
    tokens = {**pattern_tokens, **keyword_tokens}
    clauses = resolve_intent(tokens)
    
    mongo_filter = {}
    and_conditions = []
    text_queries = set()
    
    def translate_clause(c):
        if "match" in c:
            for field, val in c["match"].items():
                query_str = val["query"] if isinstance(val, dict) else val
                text_queries.add(query_str)
            return None
        elif "term" in c:
            for field, val in c["term"].items():
                return {field: val}
        elif "range" in c:
            for field, val in c["range"].items():
                range_cond = {}
                if "gte" in val: range_cond["$gte"] = val["gte"]
                if "lte" in val: range_cond["$lte"] = val["lte"]
                return {field: range_cond}
        elif "bool" in c:
            if "should" in c["bool"]:
                or_conds = []
                for sc in c["bool"]["should"]:
                    if "bool" in sc and "must" in sc["bool"]:
                        inner_and = []
                        for ic in sc["bool"]["must"]:
                            tc = translate_clause(ic)
                            if tc: inner_and.append(tc)
                        if inner_and:
                            or_conds.append({"$and": inner_and} if len(inner_and) > 1 else inner_and[0])
                if or_conds:
                    return {"$or": or_conds}
        return None

    for c in clauses["must"]:
        tc = translate_clause(c)
        if tc: and_conditions.append(tc)
        
    for c in clauses["filter"]:
        tc = translate_clause(c)
        if tc: and_conditions.append(tc)

    if clauses["should"]:
        should_conds = []
        for c in clauses["should"]:
            tc = translate_clause(c)
            if tc: should_conds.append(tc)
        if should_conds:
            and_conditions.append({"$or": should_conds})

    if text_queries:
        and_conditions.append({"$text": {"$search": " ".join(text_queries)}})
        
    if and_conditions:
        if len(and_conditions) == 1:
            mongo_filter = and_conditions[0]
        else:
            mongo_filter = {"$and": and_conditions}

    return SearchRequest(
        query=mongo_filter,
        sort=[{"avg_rating": -1}, {"_id": 1}],
        search_after=cursor,
        size=page_size,
        source_fields=[
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
            "opening_name",
            "num_moves",
            "avg_material_swings",
            "piece_sacrifices",
            "entered_endgame",
            "event",
            "pgn_moves",
            "endgame_type"
        ],
        debug_tokens={
            "raw_query": query_string,
            "pattern_tokens": pattern_tokens,
            "keyword_tokens": keyword_tokens,
        },
        debug_filter=clauses["filter"],
        debug_must=clauses["must"],
        debug_should=clauses["should"],
    )
