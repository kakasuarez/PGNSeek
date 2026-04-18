"""
app/search/index.py

Elasticsearch index mapping + alias management.
This is the schema contract — change it only via reindex (create new version, swap alias).

Design decisions encoded here:
  - All player name fields are dual: text (fuzzy) + .keyword (exact/aggregation)
  - opening_name uses the 'english' analyzer for stemming ("attacking" → "attack")
  - game_hash is used as the ES document _id — enables idempotent reingestion
  - All computed features are flat numeric fields (no nested objects)
  - Index is always accessed via alias, never by version name directly
"""

from elasticsearch import Elasticsearch, NotFoundError
from app.config import settings
import structlog

log = structlog.get_logger()

# ── Version strategy ────────────────────────────────────────────────────────
# Always create chess_games_v{N}. Alias "chess_games" points to the current version.
# To reindex: create v{N+1}, populate, swap alias, delete v{N}.
CURRENT_INDEX_VERSION = "chess_games_v1"
ALIAS_NAME = settings.ES_INDEX_ALIAS


INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 0,          # single node — replicas would just waste disk
        "refresh_interval": "30s",        # batch indexing: don't refresh after every doc
        "analysis": {
            "analyzer": {
                "opening_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "english_stemmer", "synonym_filter"]
                }
            },
            "filter": {
                "english_stemmer": {
                    "type": "stemmer",
                    "language": "english"
                },
                "synonym_filter": {
                    "type": "synonym",
                    "synonyms": [
                        # Opening name synonyms — expand as needed
                        "kid, king's indian, kings indian",
                        "qgd, queen's gambit declined",
                        "qga, queen's gambit accepted",
                        "rl, ruy lopez, spanish game",
                        "nimzo, nimzo-indian, nimzo indian",
                    ]
                }
            }
        }
    },
    "mappings": {
        "dynamic": "strict",              # reject unknown fields — schema is explicit
        "properties": {

            # ── Identity ───────────────────────────────────────────────────
            # game_hash is used as the ES _id (set during bulk indexing)
            # Storing it as a field too makes it queryable and visible in _source
            "game_hash":     {"type": "keyword"},

            # ── Player fields ──────────────────────────────────────────────
            # Dual mapping: text for fuzzy search, .keyword for exact + aggregation
            "white":         {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "black":         {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "white_elo":     {"type": "integer"},
            "black_elo":     {"type": "integer"},
            "avg_rating":    {"type": "float"},   # (white_elo + black_elo) / 2

            # ── Game outcome ───────────────────────────────────────────────
            "result":        {"type": "keyword"},  # "1-0" | "0-1" | "1/2-1/2"

            # ── Temporal ───────────────────────────────────────────────────
            "date":          {"type": "date", "format": "yyyy.MM.dd||yyyy.MM||yyyy||strict_date_optional_time"},
            "year":          {"type": "integer"},

            # ── Opening ────────────────────────────────────────────────────
            "eco":           {"type": "keyword"},  # ECO code e.g. "B20"
            "eco_prefix":    {"type": "keyword"},  # First letter only e.g. "B" (for broad category filter)
            "opening_name":  {
                "type": "text",
                "analyzer": "opening_analyzer",    # stemmed + synonyms
                "fields": {
                    "keyword": {"type": "keyword"}  # exact match on full opening name
                }
            },

            # ── Game structure ─────────────────────────────────────────────
            "num_moves":          {"type": "integer"},
            "opening_moves":      {"type": "integer"},  # moves until out of opening book
            "pgn_moves": {"type": "text", "index": "false"}, # do not index the individual moves to save space

            # ── Computed chess features ────────────────────────────────────
            # These are computed once at index time. All queries are just numeric comparisons.
            "avg_material_swings":   {"type": "float"},   # proxy for aggression / tactical sharpness
            "max_material_swing":    {"type": "float"},   # single largest swing (catches decisive moments)
            "piece_sacrifices":      {"type": "integer"}, # count of moves with swing >= SACRIFICE_DELTA
            "entered_endgame":       {"type": "boolean"}, # queens off + <= ENDGAME_MAX_PIECES total
            "endgame_move":          {"type": "integer"}, # which move the endgame started (-1 if no endgame)
            "endgame_type":          {"type": "keyword"}, # "queen" | "rook" | "minor_piece" | "pawn" | "none"
            "pawn_structure_changes":{"type": "integer"}, # pawn captures (proxy for structural play)

            # ── Source metadata ────────────────────────────────────────────
            "source_file":   {"type": "keyword"},  # which PGN file this game came from
            "event":         {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "site":          {"type": "keyword"},
        }
    }
}


def get_es_client() -> Elasticsearch:
    return Elasticsearch(settings.ES_HOST)


def setup_index(es: Elasticsearch) -> None:
    """
    Create the versioned index and alias if they don't exist.
    Safe to call multiple times — idempotent.
    """
    if not es.indices.exists(index=CURRENT_INDEX_VERSION):
        log.info("creating_index", index=CURRENT_INDEX_VERSION)
        es.indices.create(index=CURRENT_INDEX_VERSION, body=INDEX_MAPPING)
        log.info("index_created", index=CURRENT_INDEX_VERSION)
    else:
        log.info("index_already_exists", index=CURRENT_INDEX_VERSION)

    # Set up alias if it doesn't point anywhere yet
    try:
        es.indices.get_alias(name=ALIAS_NAME)
        log.info("alias_already_exists", alias=ALIAS_NAME)
    except NotFoundError:
        es.indices.put_alias(index=CURRENT_INDEX_VERSION, name=ALIAS_NAME)
        log.info("alias_created", alias=ALIAS_NAME, index=CURRENT_INDEX_VERSION)


def reindex_swap(es: Elasticsearch, new_index: str) -> None:
    """
    Atomic alias swap for zero-downtime reindexing.
    Call this after populating new_index:
        reindex_swap(es, "chess_games_v2")
    """
    actions = []

    # Remove alias from all current indices
    try:
        current = es.indices.get_alias(name=ALIAS_NAME)
        for idx in current:
            actions.append({"remove": {"index": idx, "alias": ALIAS_NAME}})
    except NotFoundError:
        pass

    # Add alias to new index
    actions.append({"add": {"index": new_index, "alias": ALIAS_NAME}})

    es.indices.update_aliases(body={"actions": actions})
    log.info("alias_swapped", alias=ALIAS_NAME, new_index=new_index)
