# PGNSeek — Design Decisions

**Project:** PGNSeek — natural language search across millions of chess games & opening review engine  
**Status:** Active  
**Last updated:** 2026-07-28  

This document is the authoritative record of every significant design decision made during the project. Before changing anything recorded here, update this document first and note the reason. Each decision includes the context, the choice made, the alternatives considered, and the consequences of changing it later.

---

## How to use this document

- **Green field decisions** — core architectural choices. Changing these requires a reindex, a migration, or an API version bump. Treat them as near-permanent.
- **MVP defaults** — chosen for the current system state with a known upgrade path.
- **Deferred** — explicitly not implemented yet. A placeholder so nothing is forgotten.

---

## 1. Data Layer

### 1.1 Storage architecture: MongoDB Atlas, Supabase Storage, and Redis

**Decision:** MongoDB Atlas is the primary database for PGNSeek. Redis is used for Celery task queuing and caching, while Supabase Storage handles temporary PGN file uploads.

**Rationale:** MongoDB Atlas provides document storage, full-text search indexing, and native Vector Search capabilities in a single managed service. This eliminated the operational overhead of running Elasticsearch while natively supporting vector similarity search for chess games.

**Collections:**
- `chess_games`: Primary game documents containing PGN metadata, computed features, and 19-dimensional feature vectors.
- `position_evals`: Cached Stockfish evaluations per normalized FEN and move.
- `review_jobs`: Asynchronous opening review job metadata, statuses, and generated reports.
- `lichess_cache`: Cached external opening explorer data with a 7-day TTL expiration index.

**Database Access:**
- FastAPI Backend: Asynchronous motor client (`AsyncIOMotorClient`) via `app/db.py`.
- Celery Workers & Ingestion CLI: Synchronous PyMongo client (`MongoClient`).

**Consequences of reversing:** High. Re-architecting data access requires updating all query logic in `app/search/mongo_executor.py` and `app/tasks.py`.

---

### 1.2 Indexing strategy: MongoDB Text Indexes and Atlas Vector Search

**Decision:** Search capabilities rely on MongoDB text indexes for keyword matching and MongoDB Atlas Vector Search for game similarity queries.

**Indexes configured:**
- Text index on `chess_games`: `opening_name`, `white`, `black`.
- Vector search index (`feature_vector_index`) on `chess_games.feature_vector`: 19 dimensions, cosine similarity.
- TTL index on `lichess_cache.fetched_at`: Expire after 604,800 seconds (7 days).
- Compound index on `review_jobs.status`.

**Vector Search Definition:**
```json
{
  "fields": [
    {
      "type": "vector",
      "path": "feature_vector",
      "numDimensions": 19,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "_id"
    }
  ]
}
```

---

### 1.3 Deduplication via game_hash as document _id

**Decision:** Every game's document `_id` is set to a 32-character SHA-256 hash derived from `White|Black|Date|Moves`. This hash is also stored as `game_hash` in document source.

**Hash input:**
```
{White}|{Black}|{Date}|{space-separated UCI moves}
```

**Rationale:** Multiple PGN source files contain duplicate games. Using `game_hash` as `_id` allows idempotent bulk upserts via `ReplaceOne({"_id": d["_id"]}, d, upsert=True)`. Re-running the pipeline on duplicate or interrupted PGN files produces zero duplicate documents.

---

### 1.4 Document Schema and 19-Dimensional Feature Vectors

**Decision:** PGN games are parsed at index time to extract both flat numeric features and a 19-dimensional dense feature vector (`feature_vector`) stored alongside each game document.

**Flat Numeric Features:**
- `avg_material_swings` (`float`): Mean material balance delta per move. High = tactical/aggressive game.
- `max_material_swing` (`float`): Largest single-move material change.
- `piece_sacrifices` (`int`): Count of exchange sequences where material was sacrificed and held.
- `entered_endgame` (`bool`): True if non-king material on both sides dropped below threshold (<= 13 points).
- `endgame_move` (`int`): Move number when endgame started (-1 if none).
- `endgame_type` (`str`): Heavy piece classification (`queen`, `rook`, `minor_piece`, `pawn`, `none`).
- `pawn_structure_changes` (`int`): Count of pawn captures.

**19-Dimensional Feature Vector Layout:**
1. `scalars` (6 dims): normalized avg material swings, piece sacrifices, average rating, game length, pawn captures, endgame proportion.
2. `endgame_type` (5 dims): one-hot encoding (`none`, `queen`, `rook`, `minor_piece`, `pawn`).
3. `result` (3 dims): weighted outcome (`1-0`, `0-1`, `1/2-1/2`).
4. `eco_prefix` (5 dims): one-hot encoding (`A`, `B`, `C`, `D`, `E`).

---

### 1.5 Features computed at index time, never at query time

**Decision:** All chess-specific features and feature vectors are pre-computed during ingestion using `python-chess`. No move traversal or feature generation happens during search queries.

**Exchange sequence sacrifice algorithm:**
The ingestion pipeline groups back-to-back capture/recapture moves into an "exchange sequence" and calculates net material change between the stable balance before and after the sequence. A sacrifice is only registered if material loss persists for quiet moves afterward, avoiding false positives on standard trades or intermediate moves (zwischenzugs).

---

### 1.6 Ingestion pipeline is resumable and checkpointed

**Decision:** The ingestion pipeline (`pipeline/ingest.py` / `backend/app/ingestion/pipeline.py`) tracks mid-file progress using byte-offset checkpointing recorded in `ingestion_state.json`.

**Resume mechanism:** When interrupted, `f.seek(byte_offset)` jumps directly to the start of the next unread game in a PGN file. Flushes happen every batch (`ES_BULK_BATCH_SIZE`, default 500), writing checkpoint state so restarts resume seamlessly without duplicate document creation.

---

## 2. Search Layer

### 2.1 Query model: deterministic three-stage pipeline to MongoDB

**Decision:** The search pipeline remains deterministic and low-latency:

1. **Token classifier** — regex patterns + keyword dictionaries → typed token dict.
2. **Intent resolver** — tokens → query clause intent (`must`, `should`, `filter`).
3. **Mongo query builder** — maps clauses into MongoDB queries (`$and`, `$or`, `$text`, range conditions `$gte`/`$lte`).

**Faceted Aggregations:** Every search execution computes faceted aggregations using MongoDB's `$facet` stage:
- Top 10 openings (`$sortByCount: "$opening_name"`)
- Top 10 results (`$sortByCount: "$result"`)
- Top 10 years (`$sortByCount: "$year"`)
- Top 10 ECO categories (derived via `$substr` on `eco`)

---

### 2.2 Vector similarity search for games

**Decision:** Similarity search for a given game hash (`GET /api/v1/games/{game_hash}/similar`) uses MongoDB Atlas `$vectorSearch` comparing the target game's `feature_vector` against the dataset.

**Pipeline:**
1. Fetch target game's `feature_vector`.
2. Run `$vectorSearch` pipeline targeting `feature_vector_index` with cosine similarity.
3. Exclude the query game (`$ne: game_hash`) and project summary fields.

---

### 2.3 Cursor-based pagination

**Decision:** Pagination uses opaque base64-encoded cursor tokens of the last document `_id` (`filter_doc["_id"] = {"$gt": last_id}`).

**Rationale:** Unlike offset pagination (`from`/`skip`), cursor pagination scales gracefully over large result sets without performance degradation on deep pages.

---

## 3. Opening Review & Asynchronous Tasks

### 3.1 Opening Review Service (Stockfish + Celery + Supabase)

**Decision:** The opening review feature processes user-uploaded PGN files asynchronously to evaluate opening positions and identify repertoire mistakes.

**Workflow:**
1. **Upload (`POST /api/v1/review`)**: Client uploads PGN file. API uploads file to Supabase Storage (`SUPABASE_BUCKET`), creates a `review_jobs` document with status `"queued"`, and dispatches `review_opening_task` to Celery via Redis broker.
2. **Worker Processing (`app.tasks.review_opening_task`)**:
   - Celery worker downloads PGN from Supabase to a temporary local file.
   - Iterates through games matching target player up to `OPENING_REVIEW_MAX_PLIES` (default 20 plies).
   - Groups unique positions by normalized FEN.
   - Evaluates positions using `AnalysisChain`: checks `position_evals` collection cache first, falling back to `CloudAnalyzer` (Lichess API) or `LocalAnalyzer` (Stockfish binary).
   - Identifies suboptimal moves where played move score loss exceeds optimal engine move score.
3. **Report Generation**: Aggregates position frequency, engine evaluations, best moves, and played move score losses into job report objects stored in `review_jobs`.
4. **Cleanup**: Temp files and Supabase storage objects are removed upon job completion or failure.

---

### 3.2 API Contract & Endpoints

**Decision:** Public API endpoints versioned under `/api/v1`:

```http
# Search Endpoints
GET /api/v1/search?q=<string>&page_size=<int>&cursor=<token>
GET /api/v1/games/<game_hash>
GET /api/v1/games/<game_hash>/similar

# Opening Review Endpoints
POST /api/v1/review (multipart/form-data: pgn_file, player)
GET  /api/v1/review/<job_id>
GET  /api/v1/review/<job_id>/reports

# Health & Diagnostic
GET /health
```

**Search Response Schema:**
```json
{
  "results": [ GameResult ],
  "total": 48201,
  "page_size": 20,
  "cursor": "base64token",
  "query_debug": { "raw_query": "...", "detected_tokens": {}, "must_clauses": [], ... },
  "aggregations": { "openings": [], "results": [], "years": [], "eco_categories": [] }
}
```

---

### 3.3 Rate Limiting and Security

**Decision:** Endpoints are rate-limited via `slowapi` at a configurable default of 60 requests/minute per IP (`RATE_LIMIT_PER_MINUTE`). CORS origins are restricted via `ALLOWED_ORIGINS`.

---

## 4. Infrastructure & Container Topology

### 4.1 Monorepo Layout

```
pgnseek/
  backend/
    app/
      api/             ← FastAPI routes (search.py, review.py, schemas.py)
      ingestion/       ← PGN parsing & feature extraction pipeline
      review/          ← Opening review schemas, analyzers, source providers
      search/          ← Natural language query parser & MongoDB executor
      config.py        ← Pydantic BaseSettings environment loader
      db.py            ← AsyncIOMotorClient database connections
      logging_config.py← Structlog JSON logging configuration
      main.py          ← FastAPI application entrypoint
      tasks.py         ← Celery worker task definitions
    Dockerfile
    requirements.txt
  pipeline/
    ingest.py          ← CLI entry point for batch data ingestion
  docker/
    docker-compose.yml ← Development service orchestration
  .env.example
  DESIGN_DECISIONS.md
```

---

### 4.2 Docker Compose Topology

`docker/docker-compose.yml` orchestrates 4 container services:

| Service | Base / Build | Port | Purpose |
|---|---|---|---|
| `redis` | `redis:7-alpine` | 6379 | Celery message broker & result backend |
| `backend` | `backend/Dockerfile` | 8000 | FastAPI application (Uvicorn) |
| `celery_worker` | `backend/Dockerfile` | — | Background task worker with Stockfish installed |
| `frontend` | `frontend/Dockerfile` | 5173 | Vite dev server |

---

### 4.3 12-Factor Configuration & Logging

- Configuration loaded via `app/config.py` using `pydantic-settings`. `.env.example` maintains the canonical list of environment variables.
- Structured logging implemented via `structlog` emitting JSON lines (`LOG_FORMAT=json`) in production and formatted output (`LOG_FORMAT=pretty`) in development.

---

## 5. Deferred Decisions

| Decision | Status / Target | Notes |
|---|---|---|
| User accounts & authentication | Post-MVP | MongoDB collection for users & JWT auth |
| Custom opening repertoire bookmarks | Post-MVP | Saved searches and user openings |
| Board position search via FEN | Phase 3 | Position exact/transposition indexing |
| LLM natural language pre-parser | Phase 3 | Fallback parser for complex queries |

---

## Changelog

| Date | Section | Change | Reason |
|---|---|---|---|
| 2026-07-28 | All | Complete update of DESIGN_DECISIONS.md | Sync document with current MongoDB Atlas, Celery/Redis, Supabase Storage, Stockfish Review Engine, and Vector Search implementation. |
| 2026-07-20 | Data Layer | Migrated from Elasticsearch to MongoDB Atlas | Single datastore for text, vectors, and document storage with lower complexity. |
| 2026-06-30 | Structure | Move Pydantic schemas into API/search feature modules | Keep code organized by responsibility. |
| 2026-04-25 | Index | Add feature vector | Similarity search support. |
| 2026-04-18 | Index | Add PGN moves | Debugging and final result detail. |
| 2026-04-14 | Index | Add endgame type | Improve endgame classification. |
| 2026-04-05 | All | Initial document created | Project kickoff. |
