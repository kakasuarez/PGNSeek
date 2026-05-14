# Meilisearch Migration Plan

PGNSeek is capped at 50,000 indexed games for the Meilisearch production path.
The current branch introduces a `SearchBackend` interface while keeping
Elasticsearch as the active implementation.

## Step 1: Stabilize The Backend Contract

- Keep API response schemas unchanged.
- Route startup, health checks, game lookup, search, similarity, and ingestion
  through `SearchBackend`.
- Keep Elasticsearch behavior as the reference implementation until the
  Meilisearch backend reaches parity.

## Step 2: Make The 50k Cap Explicit

- Use `MAX_INDEXED_GAMES=50000` as the production cap.
- Reset ingestion state before building a Meilisearch index from scratch.
- Treat `game_hash` as the primary key in both backends.

## Step 3: Add Meilisearch Infrastructure

- Add `meilisearch-python` to `requirements.txt`.
- Add Meilisearch to Docker Compose.
- Add settings:
  - `SEARCH_BACKEND=elasticsearch|meilisearch`
  - `MEILI_HOST`
  - `MEILI_MASTER_KEY`
  - `MEILI_INDEX`

## Step 4: Implement `MeilisearchSearchBackend`

- Create the index with `game_hash` as primary key.
- Configure searchable attributes:
  - `white`
  - `black`
  - `opening_name`
  - `event`
- Configure filterable attributes:
  - `result`
  - `year`
  - `eco`
  - `eco_prefix`
  - `avg_rating`
  - `num_moves`
  - `avg_material_swings`
  - `piece_sacrifices`
  - `entered_endgame`
  - `endgame_type`
- Configure sortable attributes:
  - `avg_rating`
  - `game_hash`
  - `year`
- Configure faceting for openings, results, years, and ECO categories.

## Step 5: Translate Query Semantics

- Convert the current token output into:
  - Meilisearch `q` text for opening/player search.
  - Meilisearch `filter` expressions for exact and range constraints.
  - Sort by `avg_rating:desc, game_hash:asc`.
- Replace ES `should` clauses with either ranking rules or explicit sorts.
- Keep `query_debug` populated with the original parsed tokens and translated
  Meilisearch request details.

## Step 6: Port Similarity Search

- Store the 19-dimensional feature vector in Meilisearch `_vectors`.
- Implement similar-game lookup with Meilisearch vector search.
- Exclude the source `game_hash` from returned results.

## Step 7: Validate With A 50k Corpus

- Ingest exactly 50k games.
- Compare Elasticsearch and Meilisearch results for representative queries:
  - `Sicilian white wins 2400+`
  - `Carlsen positional endgame`
  - `French defense under 30 moves draw`
  - `aggressive kings indian`
- Verify facets, total counts, pagination, game detail, and similar games.

## Step 8: Productionize

- Switch `SEARCH_BACKEND=meilisearch`.
- Keep Elasticsearch code in place until Meilisearch has been exercised on
  production-like hardware.
- Document the known tradeoff: Meilisearch is suitable for the capped 50k game
  product, while Elasticsearch/OpenSearch remains the safer path for the full
  28M game dataset.
