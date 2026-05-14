#!/usr/bin/env python3
"""
pipeline/ingest.py

CLI entry point for the ingestion pipeline.

Usage (from repo root, with venv active):
    python pipeline/ingest.py
    python pipeline/ingest.py --reset    # wipe all state and reindex from scratch
    python pipeline/ingest.py --status   # show current progress without indexing
"""

import sys
import json
import argparse
from pathlib import Path

_backend = Path(__file__).parent.parent / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import settings
from app.logging_config import configure_logging
from app.search.factory import create_search_backend
from app.ingestion.pipeline import run_pipeline, load_state, clear_state

configure_logging()


def show_status() -> None:
    state = load_state()
    print(f"\nTotal indexed  : {state.get('total_indexed', 0):,}")
    print(f"Indexing cap   : {settings.MAX_INDEXED_GAMES:,}")

    print(f"\nCompleted files : {len(state['completed'])}")
    for f in sorted(state["completed"]):
        print(f"  [done] {f}")

    print(f"\nIn-progress files: {len(state['in_progress'])}")
    for fname, info in sorted(state["in_progress"].items()):
        mb = info["byte_offset"] / 1_048_576
        print(
            f"  [resumable] {fname} — "
            f"{info['games_indexed']:,} games indexed, "
            f"offset {mb:.1f} MB, "
            f"last updated {info['last_updated']}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="PGNSeek ingestion pipeline")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear all ingestion state and reprocess every file from scratch",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current ingestion progress and exit",
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.reset:
        print("Clearing ingestion state...")
        clear_state()

    search_backend = create_search_backend()
    search_backend.setup()
    try:
        run_pipeline(search_backend)
    finally:
        search_backend.close()


if __name__ == "__main__":
    main()
