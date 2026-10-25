"""
app/review/store.py

Storage for review position trees in the `review_positions` collection.

One document per (tree_id, color, fen), unique-indexed. For uploaded PGNs the
tree_id is the review job id, and documents carry the job's `expires_at` so the
TTL index removes them together with the job. Documents without `expires_at`
never expire (for future trees synced from Lichess / Chess.com).

Document: tree_id, color, expires_at, plus the Position fields from
app/review/report.py except `line`.
"""

from datetime import datetime
from typing import Any, Iterable

import chess
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.review.report import normalize_fen

COLLECTION = "review_positions"
# Children returned with a position, most played first: covers almost every click
MAX_CHILDREN = 8
WRITE_BATCH_SIZE = 1000

# Internal fields never returned by the API
_PROJECTION = {"_id": 0, "tree_id": 0, "expires_at": 0}


async def save_positions(
    db: AsyncIOMotorDatabase,
    tree_id: str,
    positions: Iterable[tuple[str, dict[str, Any]]],
    expires_at: datetime | None,
) -> int:
    """Replace the tree's positions. Returns the number of positions saved."""
    collection = db[COLLECTION]
    # A retried job rewrites its tree from scratch
    await collection.delete_many({"tree_id": tree_id})

    saved = 0
    batch: list[dict[str, Any]] = []
    for color, position in positions:
        document = {key: value for key, value in position.items() if key != "line"}
        document.update(tree_id=tree_id, color=color)
        if expires_at is not None:
            document["expires_at"] = expires_at
        batch.append(document)
        if len(batch) >= WRITE_BATCH_SIZE:
            await collection.insert_many(batch, ordered=False)
            saved += len(batch)
            batch = []
    if batch:
        await collection.insert_many(batch, ordered=False)
        saved += len(batch)
    return saved


async def get_positions(
    db: AsyncIOMotorDatabase, tree_id: str, color: str, fens: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Positions found in the tree, keyed by normalized FEN. Missing FENs are left out."""
    cursor = db[COLLECTION].find(
        {"tree_id": tree_id, "color": color, "fen": {"$in": list(set(fens))}}, _PROJECTION
    )
    return {document["fen"]: document async for document in cursor}


def child_fens(position: dict[str, Any], limit: int = MAX_CHILDREN) -> list[str]:
    """FENs reached by the position's most played moves."""
    board = chess.Board(position["fen"])
    moves = sorted(position["played_moves"].items(), key=lambda item: -item[1]["count"])[:limit]
    fens = []
    for uci, _ in moves:
        board.push_uci(uci)
        fens.append(normalize_fen(board))
        board.pop()
    return fens


async def get_position_with_children(
    db: AsyncIOMotorDatabase, tree_id: str, color: str, fen: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """A position plus the positions after its most played moves, so the client can prefetch them."""
    found = await get_positions(db, tree_id, color, [fen])
    position = found.get(fen)
    if position is None:
        return None, []
    children = await get_positions(db, tree_id, color, child_fens(position))
    return position, list(children.values())
