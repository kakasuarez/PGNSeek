# PGNSeek — Design Decisions

**Project:** PGNSeek — natural language search across a curated chess game corpus
**Status:** Active  
**Last updated:** 2026-05-14

This document is the authoritative record of every significant design decision made during the project. Before changing anything recorded here, update this document first and note the reason. Each decision includes the context, the choice made, the alternatives considered, and the consequences of changing it later.

---

## How to use this document

- **Green field decisions** — made before any code was written. Changing these requires a reindex, a migration, or an API version bump. Treat them as near-permanent.
- **MVP defaults** — chosen for the MVP with a known upgrade path. Changing these is planned and expected.
- **Deferred** — explicitly not decided yet. A placeholder so nothing is forgotten.

---

## 1. Data Layer

### 1.1 Storage architecture: search-backend primary, PostgreSQL deferred

**Decision:** The search backend is the only datastore for the MVP. PostgreSQL is not used yet. Production is capped at 50,000 indexed games and uses Meilisearch by default. Elasticsearch remains available as a reference backend and as the safer option if the project returns to the full 28M game dataset.

**Rationale:** Every query in PGNSeek is a search operation: fuzzy text matching on player names and openings, range filters on ratings and years, numeric comparisons on computed features, facets, and similar-game lookup. At the 50k production cap, Meilisearch provides the needed feature set with lower operational complexity than Elasticsearch. PostgreSQL would add operational complexity with no benefit at this stage.

**Constraint:** The FastAPI application uses a `SearchBackend` interface. Startup, health checks, API search, game lookup, similarity, and ingestion must go through this interface rather than importing a concrete search engine directly.

**Consequences of reversing:** Moderate. PostgreSQL can be added as a second service, but replacing Meilisearch/Elasticsearch as the primary search backend requires implementing the `SearchBackend` contract and reindexing.

---

### 1.2 Search index naming and migration strategy

**Decision:** Meilisearch uses a single index named by `MEILI_INDEX` (default `chess_games`) with `game_hash` as the primary key. Elasticsearch keeps its versioned physical index plus alias strategy (`chess_games_v{N}` behind `ES_INDEX_ALIAS`) for the reference backend.

**Rationale:** Meilisearch settings are updated through index settings and the production cap is small enough that rebuilding a 50k corpus is acceptable. Elasticsearch mappings still require versioned reindexing and alias swaps.

**Meilisearch reindex procedure:**
1. Set `SEARCH_BACKEND=meilisearch`
2. Clear ingestion state with `python pipeline/ingest.py --reset`
3. Clear or recreate the Meilisearch index
4. Run ingestion until `MAX_INDEXED_GAMES` is reached

**Consequences of reversing:** Low for Meilisearch at 50k because a rebuild is cheap. High for Elasticsearch at full scale because alias-based zero-downtime swaps avoid coordinated downtime.

---

### 1.3 Deduplication via game_hash as document id

**Decision:** Every game's backend document id is a 32-character SHA-256 hash derived from `White|Black|Date|Moves`. This hash is also stored as a queryable field `game_hash`.

**Hash input:**
```
{White}|{Black}|{Date}|{space-separated UCI moves}
```

**Rationale:** Multiple PGN files (across different years of Lichess dumps, FIDE exports, etc.) will contain the same famous games. Without deduplication, the index grows unboundedly and search results contain duplicates. Using the hash as the backend document id makes every bulk index call an idempotent upsert. Elasticsearch uses `_id`; Meilisearch uses `game_hash` as the primary key.

**Limitation:** Two games between the same players on the same date with identical moves but different annotations will hash identically. This is acceptable — they are the same game.

**Consequences of reversing:** High. The idempotency guarantee disappears. Duplicate games accumulate. Resumable ingestion breaks.

---

### 1.4 Search documents are explicit and flat

**Decision:** Search documents use an explicit flat schema. All computed features are flat numeric fields (`float`, `integer`, `boolean`), never nested objects. Elasticsearch enforces this with `"dynamic": "strict"`. Meilisearch enforces behavior through explicit `displayedAttributes`, `searchableAttributes`, `filterableAttributes`, and `sortableAttributes`.

**Rationale for explicit settings:** Unknown or mistyped fields create debugging problems and can affect search relevance. Elasticsearch can reject them strictly. Meilisearch is more permissive, so the backend controls which fields are searchable, filterable, sortable, faceted, and returned by the API.

**Rationale for flat features:** Nested objects in ES require nested queries, which are significantly more expensive and complex. Every feature that informs a search (`avg_material_swings`, `piece_sacrifices`, `entered_endgame`) is a single number. Numeric range comparisons on flat fields are the cheapest possible query type in ES.

**Consequences of reversing:** Adding nested or implicit fields makes backend parity harder and requires reindexing or settings changes.

---

### 1.5 Opening name synonyms are backend-specific

**Decision:** Opening-name synonym handling is maintained per backend. Elasticsearch uses a custom analyzer with stemming and synonyms. Meilisearch uses the index `synonyms` setting and its built-in typo tolerance.

**Stemmer effect:** "attacking" → "attack", "positional" → "position", "declined" → "declin". Queries for "Sicilian attacking" match games tagged "Sicilian Attack".

**Synonym examples configured:**
- `kid, king's indian, kings indian`
- `qgd, queen's gambit declined`
- `rl, ruy lopez, spanish game`
- `nimzo, nimzo-indian, nimzo indian`

**Rationale:** Chess opening names have enormous variation in how they are written — abbreviations, hyphenation differences, possessive forms. The synonym filter encodes domain knowledge that no generic analyzer captures.

**Maintenance:** The synonym list lives in backend settings code. Adding a synonym requires updating the backend setting and reindexing or refreshing settings, depending on the backend.

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

**Decision:** The ingestion pipeline is a synchronous Python script (`pipeline/ingest.py`) that processes PGN files one at a time. Completed files are recorded in `ingestion_state.json`. The pipeline can be interrupted and restarted without reprocessing completed files. It stops at `MAX_INDEXED_GAMES` (default 50,000) for the Meilisearch production path.

**Upgrade path to async (when needed):**
- Each PGN file becomes a Celery task
- `index_pgn_file()` in `app/ingestion/pipeline.py` becomes the task body unchanged
- `ingestion_state.json` is replaced by task state in Redis

**Why not async for MVP:** Celery + Redis adds two more services and significant configuration overhead. The synchronous pipeline is easy to debug, produces clear logs, and is fast enough for the initial data load.

**Year filter:** Games with a `Date` header year below `MIN_YEAR` (default: 2010) are skipped during ingestion. This is applied at parse time before any feature computation.

**Production cap:** The ingestion state tracks `total_indexed`. When the cap is reached mid-file, that file is left resumable instead of being marked complete.

**Consequences of reversing:** Resumability is lost — killing the process means starting over.

---

## 2. Search Layer

### 2.1 Query model: deterministic three-stage pipeline

**Decision:** The query layer is fully deterministic. There is no ML model, no embeddings, no LLM at query time (in the MVP). The pipeline has three stages:

1. **Token classifier** — regex patterns + keyword dictionaries → typed token dict
2. **Intent resolver** — tokens → backend-neutral intent plus ES clause types
3. **Query builder** — assemble backend request; ES still receives a bool query body

**Upgrade path:**
- **Phase 2:** Add an LLM preprocessing step that converts a free-text query to a structured JSON of detected filters. The JSON feeds into Stage 2 unchanged. This adds latency (~300ms) but dramatically improves recall for unusual phrasings.
- **Phase 3:** Fine-tune a chess-domain embedding model for semantic game similarity ("find me games like this one").

**Why deterministic for MVP:** Predictable behavior, zero latency overhead, fully debuggable via `query_debug` in the API response. When a search returns wrong results, the cause is always visible in the debug output.

**Consequences of reversing (going LLM-first):** Non-deterministic behavior, latency dependency on external API, cost per query.

---

### 2.2 Query intent semantics

**Decision:** Each detected token type maps to consistent backend intent. Elasticsearch receives ES bool clauses. Meilisearch receives a text query, filter expressions, facets, and sort instructions derived from the same tokens.

| Token type | Elasticsearch | Meilisearch | Rationale |
|---|---|---|---|
| Opening name | `must` → `match` with fuzziness | `q` restricted to `opening_name` | Scored — relevance matters |
| Player name | `must` → `match` with fuzziness | `q` restricted to `white` and/or `black` | Scored — typo tolerance matters |
| Result | `filter` → `term` | `filter` expression | Binary — either matched or not |
| Rating range | `filter` → `range` | `filter` expression | Binary — either in range or not |
| Year | `filter` → `term` | `filter` expression | Binary |
| Style tags (aggressive, positional) | `should` → `range` on feature field | style-aware sort on feature field | Soft preference without excluding games |
| Move count | `filter` → `range` | `filter` expression | Binary |

**Key principle:** Binary constraints remain filters. Text constraints remain scored search. Style terms affect ranking but do not filter results out.

**Consequences of reversing:** Treating style as a hard filter can make normal queries look broken. Treating binary fields as text reduces precision and makes facets harder to trust.

---

### 2.3 Pagination

**Decision:** The API keeps a single opaque `cursor` field. Elasticsearch uses `search_after` with a composite sort key of `[avg_rating DESC, _id ASC]`. Meilisearch uses a base64-encoded JSON offset cursor.

**Rationale:** Elasticsearch needs `search_after` for the full dataset path. Meilisearch's production path is capped at 50k games and its documented pagination model is `offset`/`limit` or `page`/`hitsPerPage`. The Meilisearch index sets `pagination.maxTotalHits` to the production cap.

**Cursor encoding:** Opaque to clients. ES cursors encode sort values. Meilisearch cursors encode `{"offset": N}`.

**Trade-off:** Meilisearch warns that raising `maxTotalHits` above the default can affect performance. The accepted tradeoff is that 50k is the product cap; if the corpus returns to millions of games, Elasticsearch/OpenSearch should be preferred.

**Consequences of reversing:** Returning to deep pagination over millions of games should use Elasticsearch/OpenSearch or another backend with cursor pagination designed for that scale.

---

### 2.4 Facets included in every search response

**Decision:** Every search response includes an `aggregations` object with counts for: top openings in results, result distribution (white/black/draw), year distribution, ECO category distribution.

**Rationale:** Elasticsearch computes these as terms aggregations. Meilisearch computes these as facet distributions over filterable attributes. The API shape stays named `aggregations` for client compatibility.

**Current definitions:** Elasticsearch definitions live in `app/search/query.py` and response mapping in `app/search/executor.py`. Meilisearch requests facets for `opening_name`, `result`, `year`, and `eco_prefix` in `app/search/meilisearch_backend.py`.

**Consequences of reversing:** The frontend loses live facet counts. This is a visible product regression.

---

### 2.5 Default scoring and ranking

**Decision:** Elasticsearch uses default BM25 scoring for `must` clauses. Meilisearch uses its built-in ranking rules and explicit sort order. Default result order is `avg_rating:desc, game_hash:asc`; style queries place the relevant computed feature before rating in the sort list.

**Why no function score in Meilisearch:** Meilisearch does not use Elasticsearch's `function_score` DSL. The MVP uses explicit sorts for predictable behavior and will tune ranking after evaluating real search logs.

---

## 3. API Layer

### 3.1 API contract: three endpoints, versioned under /api/v1

**Decision:** The public API has exactly three endpoints, and they will not change shape without a version bump to `/api/v2`.

```http
GET /api/v1/search?q=<string>&page_size=<int>&cursor=<token>
GET /api/v1/games/<game_hash>
GET /api/v1/games/<game_hash>/similar
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

**Rationale:** Without rate limiting, a misbehaving client or accidental loop in development hammers the search backend. 60 req/min is generous for a human user and restrictive for automation.

**Upgrade path:** When user accounts are added, switch from per-IP to per-token limiting.

---

### 3.3 CORS: localhost:5173 in development, configurable in production

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
      search/       ← query pipeline, backend implementations, index management
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

**Key rule:** `pipeline/ingest.py` imports directly from `backend/app/`. There is no code duplication between the ingestion CLI and the API server. The pipeline and the API share the same `config.py`, `SearchBackend` implementations, and `ingestion/pipeline.py`.

**Consequences of reversing (splitting into multiple repos):** The shared import path breaks. Config, models, and ingestion logic must be duplicated or extracted into a shared package.

---

### 4.2 All configuration via environment variables (12-factor)

**Decision:** Every runtime configuration value lives in `.env` and is loaded via `app/config.py` (Pydantic `BaseSettings`). No value is hardcoded anywhere in the application code. Dev and prod differ only in their `.env` files, not in code paths.

**Important search variables:** `SEARCH_BACKEND`, `MEILI_HOST`, `MEILI_MASTER_KEY`, `MEILI_INDEX`, `MAX_INDEXED_GAMES`, and the existing ES variables. In Railway production, `MEILI_MASTER_KEY` must be at least 16 bytes because Meilisearch production mode requires a master key.

**Consequences of reversing:** Deployment becomes environment-specific code. Docker images are no longer portable.

---

### 4.3 Structured JSON logging via structlog

**Decision:** All application logging uses `structlog` configured to emit JSON lines in production (`LOG_FORMAT=json`) and coloured human-readable output in development (`LOG_FORMAT=pretty`).

**Required fields on every log line:** `event`, `level`, `timestamp`.

**Convention:** Log at `INFO` for normal operations (file indexed, search executed), `WARNING` for recoverable issues (malformed PGN game, unknown field in document), `ERROR` for failures that need investigation.

**Consequences of reversing:** Log aggregation tools (Datadog, CloudWatch, Loki) cannot parse unstructured log lines. Debugging production issues becomes significantly harder.

---

### 4.4 Docker Compose service topology

**Decision:** Local Docker Compose supports Meilisearch as the default production-like search service, while keeping Elasticsearch and Kibana for comparison/reference work:

| Service | Image | Port | Notes |
|---|---|---|---|
| `meilisearch` | getmeili/meilisearch:v1 | 7700 | Default local search backend for the 50k production path |
| `elasticsearch` | elasticsearch:8.13.0 | 9200 | Security disabled for local dev. `xpack.security.enabled=false` |
| `kibana` | kibana:8.13.0 | 5601 | Dev only — inspect index, run queries manually |
| `backend` | Built from `backend/Dockerfile` | 8000 | `--reload` flag on in dev |
| `frontend` | Built from `frontend/Dockerfile` | 5173 | Vite dev server with HMR |

**ES memory:** JVM heap set to 1GB (`-Xms1g -Xmx1g`). Sufficient for development and moderate data volumes. Increase in production.

**Meilisearch security:** Local Compose uses `MEILI_ENV=development` and a local default key. Production must use `MEILI_ENV=production` for the Meilisearch service and provide `MEILI_MASTER_KEY`.

**Railway:** The backend is configured with `railway.toml`, `backend/Dockerfile`, and a root `.dockerignore`. Railway supplies the `PORT` environment variable, and the backend container starts Uvicorn on `0.0.0.0:${PORT:-8000}`.

**Kibana rationale:** Not used in production, but invaluable during development for inspecting the index mapping, running Kibana Query Language queries against real data, and verifying that computed features are correct.

---

## 5. Deferred Decisions

These are explicitly not decided yet. They are recorded here so they are not forgotten.

| Decision | When to decide | Notes |
|---|---|---|
| User accounts and saved searches | Post-MVP | Will require PostgreSQL |
| Authentication model (JWT vs API keys) | When user accounts are added | — |
| Production deployment target | MVP default chosen | Railway for backend; Meilisearch may be Railway-hosted or external |
| Celery + Redis for async ingestion | When processing > 10 PGN files at once | Upgrade path is documented in §1.7 |
| PGN viewer in search results | Frontend phase 2 | Requires react-chessboard integration |
| Board position search via FEN | Phase 3 | Requires position hashing at index time |
| Full 28M game dataset | If product needs full corpus | Prefer Elasticsearch/OpenSearch or another backend with stronger deep pagination |
| Synonym management UI/file | After search tuning | Current synonyms live in backend settings code |

---

## Changelog

| Date | Section | Change | Reason |
|---|---|---|---|
| 2026-05-14 | Search/Data/Infra | Switch production path to Meilisearch with 50k cap and `SearchBackend` abstraction | Reduce production ops complexity for capped dataset |
| 2026-04-25 | Index | Add feature vector | Similarity search |
| 2026-04-18 | Index | Add PGN moves | Debugging and final result |
| 2026-04-14 | Index | Add endgame type | Improve endgame detection |
| 2026-04-05 | All | Initial document created | Project kickoff |
