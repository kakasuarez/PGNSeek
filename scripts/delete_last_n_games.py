#!/usr/bin/env python3
"""Delete the last n=50,000 documents from the chess_games collection.

Run from the repository root with the backend environment configured:
    python scripts/delete_last_n_games.py

MongoDB does not assign an insertion timestamp to the ingestion documents,
so "last" is defined here as reverse natural storage order.
"""

from pathlib import Path
import sys

from pymongo import MongoClient

_backend = Path(__file__).parent.parent / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.config import settings

DELETE_COUNT = 50_000


def main() -> None:
    with MongoClient(settings.MONGODB_URI) as client:
        collection = client[settings.MONGODB_DB]["chess_games"]
        document_ids = collection.find({}, {"_id": 1}, sort=[("$natural", -1)]).limit(
            DELETE_COUNT
        )
        ids = [document["_id"] for document in document_ids]

        if not ids:
            print("No documents found; nothing deleted.")
            return

        result = collection.delete_many({"_id": {"$in": ids}})
        print(f"Deleted {result.deleted_count:,} of {len(ids):,} selected documents.")


if __name__ == "__main__":
    main()
