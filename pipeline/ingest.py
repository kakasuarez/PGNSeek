#!/usr/bin/env python3
"""
pipeline/ingest.py

CLI entry point for the ingestion pipeline.

Usage (from repo root):
    python pipeline/ingest.py
    python pipeline/ingest.py --reset   # clear state and reindex everything

The pipeline is resumable: completed files are tracked in ingestion_state.json.
Ctrl+C at any point — the next run picks up where it left off.
"""

import sys
import argparse
from pathlib import Path

# Allow importing from backend/app/
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.config import settings
from app.logging_config import configure_logging
from app.search.index import get_es_client, setup_index
from app.ingestion.pipeline import run_pipeline, save_state

configure_logging()

def main():
    parser = argparse.ArgumentParser(description="PGNSeek ingestion pipeline")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear ingestion state and reprocess all files from scratch",
    )
    args = parser.parse_args()

    if args.reset:
        print("Resetting ingestion state...")
        save_state(set())

    es = get_es_client()
    setup_index(es)
    run_pipeline(es)


if __name__ == "__main__":
    main()
