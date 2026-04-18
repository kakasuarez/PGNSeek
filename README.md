# PGNSeek - Search chess games using natural language

## Features

- Natural language search across chess games.
- Add your own games.
- Filter by opening, players, ratings, results.

## Architecture Overview

1. PGN files are parsed by the ingestion pipeline, features are computed and indexed into Elasticsearch.
2. The FastAPI backend exposes a search API that runs a three-stage query pipeline.
3. You can read more about the decisions made [here](DESIGN_DECISIONS.md).

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
   docker compose up -d elasticsearch kibana
   ```
   Verify that they are running by running `curl http://localhost:9200/_cluster/health`. Note that the first run downloads ~1.5GB and might take some time.
5. Extract and ingest the PGN data: By default you should put your pgn files in `/data/pgn/`. Then run

   ```
   source backend/venv/bin/activate
   python pipeline/ingest.py
   ```

6. Run the backend: `uvicorn app.main:app --reload --port 8000`. You can try out the APIs at the FastAPI documentation at `http://127.0.0.1:8000/docs`.

## Workflow

1. To reset everything cleanly run `docker compose down -v` to wipe ES data and `python pipeline/ingest.py --reset` to clear ingestion state.
