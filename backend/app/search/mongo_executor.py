import base64
import structlog
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.search.query import SearchRequest
from app.search.schemas import (
    SearchResponse,
    GameResult,
    Aggregations,
    QueryDebug,
    BucketCount,
)

log = structlog.get_logger()

def _encode_cursor(doc_id: str) -> str:
    return base64.urlsafe_b64encode(doc_id.encode()).decode()

def _decode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor.encode()).decode()

async def execute_search(db: AsyncIOMotorDatabase, req: SearchRequest) -> SearchResponse:
    collection = db["chess_games"]
    
    filter_doc = req.query.copy() if req.query else {}
    
    if req.search_after:
        last_id = _decode_cursor(req.search_after)
        if "_id" not in filter_doc:
            filter_doc["_id"] = {"$gt": last_id}
        else:
            filter_doc = {"$and": [filter_doc, {"_id": {"$gt": last_id}}]}

    # Default sort for pagination
    sort = [("_id", 1)]
    
    # Compute aggregations using $facet
    base_query = req.query if req.query else {}
    facet_pipeline = [
        {"$match": base_query},
        {"$facet": {
            "openings": [{"$sortByCount": "$opening_name"}, {"$limit": 10}],
            "results": [{"$sortByCount": "$result"}, {"$limit": 10}],
            "years": [{"$sortByCount": "$year"}, {"$limit": 10}],
            "eco_categories": [
                {"$group": {"_id": {"$substr": ["$eco", 0, 1]}, "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
        }}
    ]
    
    facet_cursor = collection.aggregate(facet_pipeline)
    facet_docs = await facet_cursor.to_list(length=1)
    aggs_data = facet_docs[0] if facet_docs else {}
    
    def _map_buckets(buckets: list) -> list[BucketCount]:
        return [BucketCount(key=str(b["_id"]), count=b["count"]) for b in buckets if b.get("_id") is not None]

    aggs = Aggregations(
        openings=_map_buckets(aggs_data.get("openings", [])),
        results=_map_buckets(aggs_data.get("results", [])),
        years=_map_buckets(aggs_data.get("years", [])),
        eco_categories=_map_buckets(aggs_data.get("eco_categories", [])),
    )

    # Note: count_documents can be slow on large datasets, 
    # but without ES we must do a count if total is needed.
    # To keep pagination working properly we count the base query.
    total = await collection.count_documents(base_query)
    
    if req.source_fields:
        projection = {field: 1 for field in req.source_fields}
        projection["_id"] = 1
        cursor = collection.find(filter_doc, projection)
    else:
        cursor = collection.find(filter_doc)
        
    cursor = cursor.sort(sort).limit(req.size)
    docs = await cursor.to_list(length=req.size)
    
    results = []
    for doc in docs:
        if "game_hash" not in doc:
            doc["game_hash"] = str(doc.get("_id"))
        results.append(GameResult(**doc))
        
    next_cursor = None
    if docs and len(docs) == req.size:
        next_cursor = _encode_cursor(str(docs[-1]["_id"]))

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

async def get_game_by_hash(db: AsyncIOMotorDatabase, game_hash: str) -> dict | None:
    doc = await db["chess_games"].find_one({"_id": game_hash})
    if doc:
        if "game_hash" not in doc:
            doc["game_hash"] = doc["_id"]
    return doc

async def build_similarity_query(db: AsyncIOMotorDatabase, game_hash: str, size: int = 10) -> list:
    source = await db["chess_games"].find_one({"_id": game_hash})
    if not source:
        return []
        
    query_vector = source.get("feature_vector")
    if not query_vector:
        return []
        
    pipeline = [
        {
            "$vectorSearch": {
                "index": "feature_vector_index",
                "path": "feature_vector",
                "queryVector": query_vector,
                "numCandidates": size * 10,
                "limit": size,
                "filter": {"_id": {"$ne": game_hash}}
            }
        },
        {
            "$project": {
                "white": 1,
                "black": 1,
                "opening_name": 1,
                "result": 1,
                "avg_rating": 1,
                "avg_material_swings": 1,
                "piece_sacrifices": 1,
                "game_hash": 1,
                "pgn_moves": 1,
                "_id": 0
            }
        }
    ]
    
    cursor = db["chess_games"].aggregate(pipeline)
    return await cursor.to_list(length=size)
