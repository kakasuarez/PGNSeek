# PGNSeek — Design Decisions

**Project:** PGNSeek — natural language search across millions of chess games  
**Status:** Active  
**Last updated:** 2026-04-18

This document is the authoritative record of every significant design decision made during the project. Before changing anything recorded here, update this document first and note the reason. Each decision includes the context, the choice made, the alternatives considered, and the consequences of changing it later.

---

## How to use this document

- **Green field decisions** — made before any code was written. Changing these requires a reindex, a migration, or an API version bump. Treat them as near-permanent.
- **MVP defaults** — chosen for the MVP with a known upgrade path. Changing these is planned and expected.
- **Deferred** — explicitly not decided yet. A placeholder so nothing is forgotten.

---

## 1. Data Layer

### 1.1 Storage architecture: Elasticsearch-primary, PostgreSQL deferred

**Decision:** Elasticsearch is the only datastore for the MVP. PostgreSQL is not used yet.

**Rationale:** Every query in PGNSeek is a search operation — fuzzy text matching on player names and openings, range filters on ratings and years, numeric comparisons on computed features. Elasticsearch handles all of these natively. PostgreSQL would add operational complexity with no benefit at this stage.

**Constraint:** The FastAPI application and Docker Compose are structured as if PostgreSQL exists (a `db` service slot is reserved in Compose, Pydantic models are kept separate from ES-specific logic). Adding PostgreSQL for user accounts, saved searches, or job tracking in a later phase requires no architectural changes.

**Consequences of reversing:** Low. PostgreSQL can be added as a second service. No existing code needs to change.

---

### 1.2 Index versioning and alias strategy

**Decision:** The physical ES index is always named `chess_games_v{N}` (starting at `chess_games_v1`). All application queries hit the alias `chess_games`, which points to the current version. The alias name is what goes in `.env` as `ES_INDEX_ALIAS`.

**Rationale:** Changing the index mapping (adding a field type, changing an analyzer) requires creating a new index and reindexing all documents. Without an alias, this requires a coordinated downtime window. With an alias, the swap is atomic — one `update_aliases` call moves traffic from the old index to the new one with zero downtime.

**Reindex procedure:**
1. Create `chess_games_v2` with the new mapping
2. Run the ingestion pipeline targeting `chess_games_v2`
3. Call `reindex_swap(es, "chess_games_v2")` — atomic alias swap
4. Delete `chess_games_v1`

**Consequences of reversing:** Breaking. All search and ingestion code references the alias, not the versioned index. Removing the alias layer means hardcoding an index name everywhere.

---

### 1.3 Deduplication via game_hash as document _id

**Decision:** Every game's Elasticsearch `_id` is set to a 32-character SHA-256 hash derived from `White|Black|Date|Moves`. This hash is also stored as a queryable field `game_hash` in `_source`.

**Hash input:**
```
{White}|{Black}|{Date}|{space-separated UCI moves}
```

**Rationale:** Multiple PGN files (across different years of Lichess dumps, FIDE exports, etc.) will contain the same famous games. Without deduplication, the index grows unboundedly and search results contain duplicates. Using the hash as `_id` makes every bulk index call an idempotent upsert — rerunning the pipeline on a file that was already processed produces no side effects.

**Limitation:** Two games between the same players on the same date with identical moves but different annotations will hash identically. This is acceptable — they are the same game.

**Consequences of reversing:** High. The idempotency guarantee disappears. Duplicate games accumulate. Resumable ingestion breaks.

---

### 1.4 ES index mapping is strict and flat

**Decision:** The index mapping uses `"dynamic": "strict"` — unknown fields are rejected, not silently indexed. All computed features are flat numeric fields (`float`, `integer`, `boolean`), never nested objects.

**Rationale for strict:** Unknown fields silently indexed into ES cause mapping conflicts when the field appears with different types across documents. Failing loudly at index time is better than discovering a corrupted mapping at query time.

**Rationale for flat features:** Nested objects in ES require nested queries, which are significantly more expensive and complex. Every feature that informs a search (`avg_material_swings`, `piece_sacrifices`, `entered_endgame`) is a single number. Numeric range comparisons on flat fields are the cheapest possible query type in ES.

**Consequences of reversing:** Adding a nested field requires a mapping change (reindex). Dynamic mapping means unexpected fields silently appear in the index — debugging becomes harder.

---

### 1.5 Opening name field uses the english analyzer with synonyms

**Decision:** The `opening_name` field uses a custom analyzer (`opening_analyzer`) that applies the English stemmer and a hand-maintained synonym filter.

**Stemmer effect:** "attacking" → "attack", "positional" → "position", "declined" → "declin". Queries for "Sicilian attacking" match games tagged "Sicilian Attack".

**Synonym examples configured:**
- `kid, king's indian, kings indian`
- `qgd, queen's gambit declined`
- `rl, ruy lopez, spanish game`
- `nimzo, nimzo-indian, nimzo indian`

**Rationale:** Chess opening names have enormous variation in how they are written — abbreviations, hyphenation differences, possessive forms. The synonym filter encodes domain knowledge that no generic analyzer captures.

**Maintenance:** The synonym list lives in the index mapping (`app/search/index.py`). Adding a synonym requires a mapping update and reindex, or using a synonym file on disk (the production upgrade path).

**Consequences of reversing:** Search recall drops significantly for opening queries. Users who type "KID" get no results for King's Indian games.

---

### 1.6 Features are computed at index time, never at query time

**Decision:** All chess-specific features (`avg_material_swings`, `max_material_swing`, `piece_sacrifices`, `entered_endgame`, `endgame_move`, `pawn_structure_changes`) are computed during ingestion by traversing the move tree with `python-chess`. They are stored as flat numeric fields. No chess computation happens at query time.

**Rationale:** `python-chess` move traversal on a 60-move game takes approximately 2–5ms. At query time, this would need to run on thousands of candidate documents — making every search take seconds. At index time, it runs once per game and is never repeated (dedup ensures this).

**Current feature set and their search semantics:**

| Field | Type | Semantics |
|---|---|---|
| `avg_material_swings` | float | Mean material balance delta per move. High = tactical/aggressive game |
| `max_material_swing` | float | Largest single-move material change. Catches decisive sacrifices |
| `piece_sacrifices` | integer | Count of moves where material swing ≥ `SACRIFICE_DELTA` (default: 3 points) |
| `entered_endgame` | boolean | True if queens left the board and total pieces ≤ `ENDGAME_MAX_PIECES` (default: 12) |
| `endgame_move` | integer | Move number when endgame started. -1 if no endgame detected |
| `endgame_type` | keyword | Which piece endgame it is. |
| `pawn_structure_changes` | integer | Count of pawn captures — proxy for pawn structure complexity |

**Tuning:** All thresholds (`SACRIFICE_DELTA`, `ENDGAME_MAX_PIECES`, `AGGRESSION_THRESHOLD`) are environment variables in `.env`. They can be adjusted without code changes, but reindexing is required to apply new values to existing documents.

**Consequences of reversing:** Search latency becomes untenable at scale.

---

### 1.7 Ingestion pipeline is synchronous and resumable

**Decision:** The ingestion pipeline is a synchronous Python script (`pipeline/ingest.py`) that processes PGN files one at a time. Completed files are recorded in `ingestion_state.json`. The pipeline can be interrupted and restarted without reprocessing completed files.

**Upgrade path to async (when needed):**
- Each PGN file becomes a Celery task
- `index_pgn_file()` in `app/ingestion/pipeline.py` becomes the task body unchanged
- `ingestion_state.json` is replaced by task state in Redis

**Why not async for MVP:** Celery + Redis adds two more services and significant configuration overhead. The synchronous pipeline is easy to debug, produces clear logs, and is fast enough for the initial data load.

**Year filter:** Games with a `Date` header year below `MIN_YEAR` (default: 2010) are skipped during ingestion. This is applied at parse time before any feature computation.

**Consequences of reversing:** Resumability is lost — killing the process means starting over.

---

## 2. Search Layer

### 2.1 Query model: deterministic three-stage pipeline

**Decision:** The query layer is fully deterministic. There is no ML model, no embeddings, no LLM at query time (in the MVP). The pipeline has three stages:

1. **Token classifier** — regex patterns + keyword dictionaries → typed token dict
2. **Intent resolver** — tokens → ES clause types (must / should / filter / must_not)
3. **Query builder** — clauses → ES bool query body

**Upgrade path:**
- **Phase 2:** Add an LLM preprocessing step that converts a free-text query to a structured JSON of detected filters. The JSON feeds into Stage 2 unchanged. This adds latency (~300ms) but dramatically improves recall for unusual phrasings.
- **Phase 3:** Fine-tune a chess-domain embedding model for semantic game similarity ("find me games like this one").

**Why deterministic for MVP:** Predictable behavior, zero latency overhead, fully debuggable via `query_debug` in the API response. When a search returns wrong results, the cause is always visible in the debug output.

**Consequences of reversing (going LLM-first):** Non-deterministic behavior, latency dependency on external API, cost per query.

---

### 2.2 Clause semantics: must vs filter vs should

**Decision:** Each detected token type maps to a specific ES clause type with consistent semantics:

| Token type | ES clause | Rationale |
|---|---|---|
| Opening name | `must` → `match` with fuzziness | Scored — relevance matters. A closer match to "Sicilian" should rank higher |
| Player name | `must` → `match` with fuzziness | Scored — "Carlsen" should rank exact matches above "Carlsen-like" spellings |
| Result | `filter` → `term` | Binary — either white won or didn't. No scoring value |
| Rating range | `filter` → `range` | Binary — either in range or not |
| Year | `filter` → `term` | Binary |
| Style tags (aggressive, positional) | `should` → `range` on feature field | Soft preference — boosts matching games, doesn't exclude non-matching ones |
| Move count | `filter` → `range` | Binary |

**Key principle:** `filter` clauses are cached by ES and contribute zero scoring overhead. Use `filter` for anything binary. Use `must` only when ranking by relevance to the term matters. Use `should` for soft preferences that should boost score without excluding results.

**Consequences of reversing:** Putting everything in `must` means a query for "aggressive Sicilian" returns zero results if no game is tagged both — instead of returning Sicilian games boosted by aggressiveness score.

---

### 2.3 Pagination: search_after, not from/size

**Decision:** Pagination uses ES `search_after` with a composite sort key of `[avg_rating DESC, _id ASC]`. The cursor returned in the API response is a base64-encoded JSON array of the last hit's sort values. Clients pass this as the `cursor` query parameter on the next request.

**Rationale:** ES refuses `from/size` queries where `from + size > index.max_result_window` (default 10,000). With millions of games, users who page deep will hit this wall. `search_after` has no depth limit.

**Cursor encoding:** `base64(json([avg_rating_value, "_id_value"]))` — opaque to clients.

**Trade-off:** `search_after` cursors are not stable if new documents are indexed between requests. For a search tool this is acceptable — unlike e-commerce, users don't need perfectly consistent pagination across writes.

**Consequences of reversing:** Results break for any user paging beyond result 10,000. Error is a hard 400 from ES, not a graceful degradation.

---

### 2.4 Aggregations included in every search response

**Decision:** Every search response includes an `aggregations` object with counts for: top openings in results, result distribution (white/black/draw), year distribution, ECO category distribution.

**Rationale:** Aggregations are computed by ES in the same query as the search — there is no second round trip. The cost is minimal. The UX benefit is large: the frontend can render faceted filter chips ("Sicilian: 3,421 | French: 812") that update with every query. This is the feature that makes the product feel like a real search engine rather than a list of results.

**Current agg definitions:** Implemented in `app/search/executor.py`. Top 10 buckets per aggregation.

**Consequences of reversing:** The frontend loses live facet counts. This is a visible product regression.

---

### 2.5 Default scoring: BM25 with planned function_score upgrade

**Decision:** The MVP uses ES's default BM25 scoring for `must` clauses. A `function_score` wrapper will be added in the first post-MVP sprint to boost results by `avg_rating` and `avg_material_swings` when style queries are present.

**Planned function_score shape:**
```json
{
  "function_score": {
    "query": { "bool": { ... } },
    "functions": [
      { "field_value_factor": { "field": "avg_material_swings", "factor": 1.5, "modifier": "log1p" } }
    ],
    "boost_mode": "multiply"
  }
}
```

**Why deferred:** Default BM25 produces acceptable results for the MVP. Tuning `function_score` requires seeing real query results first — premature optimization here produces worse results than waiting for data.

---

## 3. API Layer

### 3.1 API contract: two endpoints, versioned under /api/v1

**Decision:** The public API has exactly two endpoints, and they will not change shape without a version bump to `/api/v2`.

```
GET /api/v1/search?q=<string>&page_size=<int>&cursor=<token>
GET /api/v1/games/<game_hash>
GET /health   (unversioned — infrastructure concern)
```

**Search response envelope (permanent shape):**
```json
{
  "results":      [ GameResult ],
  "total":        48201,
  "page_size":    20,
  "cursor":       "base64token",
  "query_debug":  { "raw_query": "...", "detected_tokens": {}, "must_clauses": [], ... },
  "aggregations": { "openings": [], "results": [], "years": [], "eco_categories": [] }
}
```

**Error envelope (permanent shape):**
```json
{
  "error":   "machine_readable_code",
  "message": "Human readable explanation",
  "detail":  { "context": "key" }
}
```

**`query_debug` rationale:** Exposes what the query parser actually produced. Invaluable during development, and useful for power users who want to understand why results are ranked as they are. Can be hidden behind a `?debug=false` parameter in production if needed.

**Consequences of reversing:** Any frontend or API client built against this contract breaks.

---

### 3.2 Rate limiting: per-IP, 60 requests/minute

**Decision:** Every endpoint is rate-limited at 60 requests/minute per IP using `slowapi`. The limit is configurable via `RATE_LIMIT_PER_MINUTE` in `.env`.

**Rationale:** Without rate limiting, a misbehaving client or accidental loop in development hammers Elasticsearch. 60 req/min is generous for a human user and restrictive for automation.

**Upgrade path:** When user accounts are added, switch from per-IP to per-token limiting.

---

### 3.3 Caching: in-memory dict for MVP, Redis interface ready

**Decision:** Repeated identical queries (same `q` + `page_size` + `cursor`) are served from an in-memory LRU cache with `CACHE_TTL_SECONDS` (default: 300s) TTL and `CACHE_MAX_SIZE` (default: 1,000 entries) max size.

**Interface contract:** The cache is accessed only through a thin wrapper in `app/search/cache.py`. The wrapper's interface (`get(key)`, `set(key, value)`) is identical whether the backend is an in-memory dict or Redis. Switching to Redis requires only changing the backend inside `cache.py`.

**What is cached:** The full serialized `SearchResponse`. The cache key is `sha256(q + page_size + cursor)`.

**What is not cached:** Individual game lookups (`/games/{hash}`) — ES handles these with its own shard-level caching.

---

### 3.4 CORS: localhost:5173 in development, configurable in production

**Decision:** The `CORSMiddleware` allows `http://localhost:5173` (Vite's default dev port) in development. In production, `ALLOWED_ORIGINS` will be set as an environment variable.

---

## 4. Infrastructure

### 4.1 Monorepo structure

**Decision:** Single git repository with the following top-level layout:

```
pgnseek/
  backend/
    app/
      api/          ← FastAPI route handlers
      search/       ← query pipeline, ES index management, executor
      ingestion/    ← PGN parser, feature extractor, bulk indexer
      models/       ← Pydantic schemas (API contract)
    tests/
    Dockerfile
    requirements.txt
  frontend/
    src/
    Dockerfile
  pipeline/
    ingest.py       ← CLI entry point; imports from backend/app/
  docker/
    docker-compose.yml
  .env.example
  DESIGN_DECISIONS.md   ← this file
```

**Key rule:** `pipeline/ingest.py` imports directly from `backend/app/`. There is no code duplication between the ingestion CLI and the API server. The pipeline and the API share the same `config.py`, `index.py`, and `ingestion/pipeline.py`.

**Consequences of reversing (splitting into multiple repos):** The shared import path breaks. Config, models, and ingestion logic must be duplicated or extracted into a shared package.

---

### 4.2 All configuration via environment variables (12-factor)

**Decision:** Every runtime configuration value lives in `.env` and is loaded via `app/config.py` (Pydantic `BaseSettings`). No value is hardcoded anywhere in the application code. Dev and prod differ only in their `.env` files, not in code paths.

**The `.env.example` file is the canonical list of all configuration knobs.** When a new config value is added, `.env.example` must be updated in the same commit.

**Consequences of reversing:** Deployment becomes environment-specific code. Docker images are no longer portable.

---

### 4.3 Structured JSON logging via structlog

**Decision:** All application logging uses `structlog` configured to emit JSON lines in production (`LOG_FORMAT=json`) and coloured human-readable output in development (`LOG_FORMAT=pretty`).

**Required fields on every log line:** `event`, `level`, `timestamp`.

**Convention:** Log at `INFO` for normal operations (file indexed, search executed), `WARNING` for recoverable issues (malformed PGN game, unknown field in document), `ERROR` for failures that need investigation.

**Consequences of reversing:** Log aggregation tools (Datadog, CloudWatch, Loki) cannot parse unstructured log lines. Debugging production issues becomes significantly harder.

---

### 4.4 Docker Compose service topology

**Decision:** Four services in `docker-compose.yml`:

| Service | Image | Port | Notes |
|---|---|---|---|
| `elasticsearch` | elasticsearch:8.13.0 | 9200 | Security disabled for local dev. `xpack.security.enabled=false` |
| `kibana` | kibana:8.13.0 | 5601 | Dev only — inspect index, run queries manually |
| `backend` | Built from `backend/Dockerfile` | 8000 | `--reload` flag on in dev |
| `frontend` | Built from `frontend/Dockerfile` | 5173 | Vite dev server with HMR |

**ES memory:** JVM heap set to 1GB (`-Xms1g -Xmx1g`). Sufficient for development and moderate data volumes. Increase in production.

**Health checks:** The backend service depends on ES being healthy (HTTP cluster health check) before starting. This prevents startup failures from race conditions.

**Kibana rationale:** Not used in production, but invaluable during development for inspecting the index mapping, running Kibana Query Language queries against real data, and verifying that computed features are correct.

---

## 5. Deferred Decisions

These are explicitly not decided yet. They are recorded here so they are not forgotten.

| Decision | When to decide | Notes |
|---|---|---|
| User accounts and saved searches | Post-MVP | Will require PostgreSQL |
| Authentication model (JWT vs API keys) | When user accounts are added | — |
| Production deployment target | After MVP is stable | Render, Railway, or self-hosted |
| Celery + Redis for async ingestion | When processing > 10 PGN files at once | Upgrade path is documented in §1.7 |
| `function_score` tuning | After seeing real query results | Documented in §2.5 |
| PGN viewer in search results | Frontend phase 2 | Requires react-chessboard integration |
| Board position search via FEN | Phase 3 | Requires position hashing at index time |
| Embedding-based semantic similarity | Phase 3 | "Find games like this one" feature |
| Synonym file on disk vs inline | At next reindex | Disk-based synonyms can be updated without reindex |

---

## Changelog

| Date | Section | Change | Reason |
|---|---|---|---|
| 2026-04-25 | Index | Add feature vector | Similarity search |
| 2026-04-18 | Index | Add PGN moves | Debugging and final result |
| 2026-04-14 | Index | Add endgame type | Improve endgame detection |
| 2026-04-05 | All | Initial document created | Project kickoff |
