# PGNSeek - Search chess games using natural language

## Features

- Natural language search across chess games.
- Add your own games.
- Filter by opening, players, ratings, results.

## Architecture Overview

1. PGN files are parsed by the ingestion pipeline, features are computed and indexed into the configured search backend.
2. The FastAPI backend exposes a search API that runs a three-stage query pipeline.
3. The production-oriented backend is Meilisearch with a 50k game cap. Elasticsearch remains available as a reference backend.
4. You can read more about the decisions made [here](DESIGN_DECISIONS.md).

## Prerequisites

1. Python 3.13 [Download here](https://www.python.org/downloads/release/python-3130/)
2. Docker Desktop 4.67.0 [Download here](https://www.docker.com/products/docker-desktop/)

## Setup

1. Clone the repository: `git clone https://github.com/kakasuarez/PGNSeek.git`.
2. Create the `.env` file and edit it as needed: `cp .env.example .env`.
3. Create the virtual environment:
   ```cd backend
   python3 -m venv venv
   source venv/bin/activate
   cd ..
   pip install -r requirements.txt
   ```
4. Start the Docker services:
   ```
   cd docker
   docker compose up -d meilisearch
   ```
   Verify that it is running with `curl http://localhost:7700/health`.
5. Extract and ingest the PGN data: By default you should put your pgn files in `/data/pgn/`. Then run

   ```
   source backend/venv/bin/activate
   export SEARCH_BACKEND=meilisearch
   export MEILI_MASTER_KEY=local-development-master-key
   python pipeline/ingest.py
   ```

6. Run the backend:
   ```
   source backend/venv/bin/activate
   cd backend
   SEARCH_BACKEND=meilisearch MEILI_MASTER_KEY=local-development-master-key uvicorn app.main:app --reload --port 8000
   ```
   You can try out the APIs at the FastAPI documentation at `http://127.0.0.1:8000/docs`.

## Workflow

1. To reset everything cleanly run `docker compose down -v` to wipe search data and `python pipeline/ingest.py --reset` to clear ingestion state.

## Railway

The backend service is configured for Railway through `railway.toml` and `backend/Dockerfile`.
Set these Railway variables for the backend service:

- `SEARCH_BACKEND=meilisearch`
- `MEILI_HOST=<your Meilisearch service URL>`
- `MEILI_MASTER_KEY=<at least 16 bytes in production>`
- `MEILI_INDEX=chess_games`
- `ENV=production`

Railway provides `PORT`; the Dockerfile starts Uvicorn on `0.0.0.0:${PORT:-8000}`.
