"""
app/ingestion/pipeline.py

PGN ingestion pipeline. CLI entry point: pipeline/ingest.py

Responsibilities:
    1. Find all PGN files in PGN_DATA_DIR
    2. Resume interrupted files using byte-offset checkpointing
    3. Skip fully completed files
    4. For each file: parse games -> compute features -> bulk index to ES

State schema (ingestion_state.json):
    {
    "completed": ["file_a.pgn"],
    "in_progress": {
        "file_b.pgn": {
        "byte_offset": 1073741824,
        "games_indexed": 847500,
        "last_updated": "2026-04-18T09:39:02Z"
        }
    }
    }

Resume mechanism: f.seek(byte_offset) jumps directly to the start of the
next unread game. State is written after every bulk flush, so on crash
you re-index at most ES_BULK_BATCH_SIZE games — which is idempotent
because game_hash is used as the ES document _id.
"""

import json
import hashlib
import datetime
from pathlib import Path
from typing import Generator

import chess
import chess.pgn
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import structlog

from app.config import settings
from app.search.index import ALIAS_NAME

log = structlog.get_logger()

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

eco_to_opening = {}
with open(settings.ECO_TO_OPENING_FILE, "r") as f:
    eco_to_opening.update(json.load(f))

# -- Game hash -----------------------------------------------------------------


def compute_game_hash(game: chess.pgn.Game) -> str:
    h = game.headers
    moves = " ".join(str(m) for m in game.mainline_moves())
    canonical = (
        f"{h.get('White','')}|{h.get('Black','')}|" f"{h.get('Date','')}|{moves}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


# -- Feature extraction --------------------------------------------------------


def material_balance(board: chess.Board) -> float:
    score = 0.0
    for pt, val in PIECE_VALUES.items():
        score += len(board.pieces(pt, chess.WHITE)) * val
        score -= len(board.pieces(pt, chess.BLACK)) * val
    return score


def side_material(board: chess.Board, color: chess.Color) -> float:
    """Total non-king material for one side (used for endgame classification)."""
    return sum(
        len(board.pieces(pt, color)) * val
        for pt, val in PIECE_VALUES.items()
        if pt != chess.KING
    )


def classify_endgame_type(board: chess.Board) -> str:
    """
    Called at the moment the endgame threshold is crossed.
    Classifies by the heaviest piece still on the board (either side).
    Handles queen endgames correctly -- a lone queen IS an endgame.
    """
    if board.pieces(chess.QUEEN, chess.WHITE) or board.pieces(chess.QUEEN, chess.BLACK):
        return "queen"
    if board.pieces(chess.ROOK, chess.WHITE) or board.pieces(chess.ROOK, chess.BLACK):
        return "rook"
    if (
        board.pieces(chess.BISHOP, chess.WHITE)
        or board.pieces(chess.BISHOP, chess.BLACK)
        or board.pieces(chess.KNIGHT, chess.WHITE)
        or board.pieces(chess.KNIGHT, chess.BLACK)
    ):
        return "minor_piece"
    return "pawn"


def compute_features(game: chess.pgn.Game) -> dict:
    board = game.board()
    balances: list[float] = []
    pawn_captures = 0
    endgame_move = -1
    endgame_type = "none"

    ENDGAME_MATERIAL_THRESHOLD = 13

    for move_num, move in enumerate(game.mainline_moves(), start=1):
        if (
            board.is_capture(move)
            and board.piece_type_at(move.from_square) == chess.PAWN
        ):
            pawn_captures += 1

        board.push(move)
        bal = material_balance(board)
        balances.append(bal)

        if endgame_move == -1:
            w_mat = side_material(board, chess.WHITE)
            b_mat = side_material(board, chess.BLACK)
            if (
                w_mat <= ENDGAME_MATERIAL_THRESHOLD
                and b_mat <= ENDGAME_MATERIAL_THRESHOLD
            ):
                endgame_move = move_num
                endgame_type = classify_endgame_type(board)

    # Sacrifice detection: a trade recovers within RECOVERY_WINDOW moves.
    # A genuine sacrifice does not.
    sacrifices = 0
    SAC_DELTA = float(settings.SACRIFICE_DELTA)
    RECOVERY_WINDOW = 2
    RECOVERY_TOLERANCE = 1.0

    for i in range(len(balances) - 1):
        pre_swing_bal = balances[i - 1] if i > 0 else 0.0
        immediate_swing = abs(balances[i] - pre_swing_bal)
        if immediate_swing < SAC_DELTA:
            continue
        future_idx = min(i + RECOVERY_WINDOW, len(balances) - 1)
        recovered = abs(balances[future_idx] - pre_swing_bal) <= RECOVERY_TOLERANCE
        if not recovered:
            sacrifices += 1

    swings = [abs(balances[i] - balances[i - 1]) for i in range(1, len(balances))]
    avg_swing = sum(swings) / len(swings) if swings else 0.0
    max_swing = max(swings, default=0.0)

    return {
        "num_moves": len(balances),
        "avg_material_swings": round(avg_swing, 3),
        "max_material_swing": round(max_swing, 3),
        "piece_sacrifices": sacrifices,
        "entered_endgame": endgame_move > 0,
        "endgame_move": endgame_move,
        "endgame_type": endgame_type,
        "pawn_structure_changes": pawn_captures,
    }


# -- Document builder ----------------------------------------------------------
def build_feature_vector(doc: dict) -> list[float]:
    """
    Normalized feature vector for similarity search.
    All values scaled to approximately [0, 1].
    Order must not change after first indexing.
    """
    return [
        min(1.0, (doc.get("average_material_swings") or 0) / 8.0),
        min(1.0, (doc.get("piece_sacrifices") or 0) / 6.0),
        1.0 if doc.get("entered_endgame") else 0.0,
        min(1.0, (doc.get("num_moves") or 0) / 120.0),
        min(1.0, (doc.get("avg_rating") or 2000) / 3000.0),
        min(1.0, (doc.get("pawn_structure_changes") or 0) / 15.0),
    ]


def game_to_document(game: chess.pgn.Game, source_file: str) -> dict | None:
    h = game.headers
    game_hash = compute_game_hash(game)

    date_str = h.get("Date", "")
    try:
        year = int(date_str[:4])
    except (ValueError, TypeError):
        year = None

    if year and year < settings.MIN_YEAR:
        return None

    try:
        white_elo = int(h.get("WhiteElo", 0)) or None
        black_elo = int(h.get("BlackElo", 0)) or None
    except ValueError:
        white_elo = black_elo = None

    avg_rating = (white_elo + black_elo) / 2 if white_elo and black_elo else None

    eco = h.get("ECO", None)
    eco_prefix = eco[0] if eco else None
    features = compute_features(game)

    return {
        "game_hash": game_hash,
        "white": h.get("White", "?"),
        "black": h.get("Black", "?"),
        "white_elo": white_elo,
        "black_elo": black_elo,
        "avg_rating": avg_rating,
        "result": h.get("Result", None),
        "date": date_str if date_str != "????.??.??" else None,
        "year": year,
        "eco": eco,
        "eco_prefix": eco_prefix,
        "opening_name": eco_to_opening[eco],
        "event": h.get("Event", None),
        "site": h.get("Site", None),
        "source_file": source_file,
        "pgn_moves": " ".join(str(m) for m in game.mainline_moves()),
        **features,
    }


# -- Bulk indexing -------------------------------------------------------------


def iter_bulk_actions(documents: list[dict]) -> Generator[dict, None, None]:
    for doc in documents:
        yield {
            "_index": ALIAS_NAME,
            "_id": doc["game_hash"],
            "_source": doc,
        }


# -- Resumable state -----------------------------------------------------------


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_state() -> dict:
    state_path = Path(settings.INGESTION_STATE_FILE)
    if state_path.exists():
        raw = json.loads(state_path.read_text())
        return {
            "completed": set(raw.get("completed", [])),
            "in_progress": raw.get("in_progress", {}),
        }
    return {"completed": set(), "in_progress": {}}


def save_state(state: dict) -> None:
    state_path = Path(settings.INGESTION_STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "completed": sorted(state["completed"]),
                "in_progress": state["in_progress"],
            },
            indent=2,
        )
    )


def clear_state() -> None:
    """Reset all progress. Called by pipeline/ingest.py --reset."""
    state_path = Path(settings.INGESTION_STATE_FILE)
    if state_path.exists():
        state_path.unlink()


# -- File-level indexer --------------------------------------------------------


def index_pgn_file(es: Elasticsearch, pgn_path: Path, state: dict) -> dict:
    """
    Parse and index one PGN file with mid-file resumability.

    How resuming works:
      1. load_state() returns the saved byte_offset for this file (if any)
      2. f.seek(byte_offset) jumps directly to that position -- O(1)
      3. chess.pgn.read_game(f) continues reading from that point
      4. After every bulk flush, f.tell() gives the byte position of the
         NEXT unread game, which is saved back to state

    On crash, the next run re-indexes at most ES_BULK_BATCH_SIZE games.
    This is safe because game_hash is the ES _id -- re-indexing a game
    that was already indexed is a no-op (ES upserts it identically).
    """
    filename = pgn_path.name
    file_log = log.bind(file=filename)

    prior = state["in_progress"].get(filename, {})
    resume_offset: int = prior.get("byte_offset", 0)
    games_indexed: int = prior.get("games_indexed", 0)

    if resume_offset > 0:
        file_log.info(
            "resuming_file",
            byte_offset=resume_offset,
            games_indexed_so_far=games_indexed,
        )
    else:
        file_log.info("indexing_file")

    parsed = skipped = errors = 0
    batch: list[dict] = []

    with open(pgn_path, encoding="utf-8", errors="replace") as f:
        if resume_offset > 0:
            f.seek(resume_offset)

        while True:
            try:
                game = chess.pgn.read_game(f)
            except Exception as exc:
                file_log.warning("pgn_parse_error", error=str(exc), exc_info=True)
                errors += 1
                continue

            if game is None:
                break

            parsed += 1
            doc = game_to_document(game, source_file=filename)
            if doc is None:
                skipped += 1
                continue
            doc["feature_vector"] = build_feature_vector(doc)

            batch.append(doc)

            if len(batch) >= settings.ES_BULK_BATCH_SIZE:
                success, _ = bulk(es, iter_bulk_actions(batch), raise_on_error=False)
                games_indexed += success
                batch = []

                # Checkpoint: save current position before reading the next game.
                # f.tell() here is the byte offset of the start of the next game.
                current_offset = f.tell()
                state["in_progress"][filename] = {
                    "byte_offset": current_offset,
                    "games_indexed": games_indexed,
                    "last_updated": _now_iso(),
                }
                save_state(state)

                file_log.info(
                    "batch_flushed",
                    games_indexed=games_indexed,
                    byte_offset=current_offset,
                    skipped=skipped,
                    errors=errors,
                )

        # Final partial batch
        if batch:
            success, _ = bulk(es, iter_bulk_actions(batch), raise_on_error=False)
            games_indexed += success

    # Fully done: remove from in_progress, add to completed
    state["in_progress"].pop(filename, None)
    state["completed"].add(filename)
    save_state(state)

    summary = {
        "parsed": parsed,
        "indexed": games_indexed,
        "skipped_year": skipped,
        "errors": errors,
    }
    if errors > 0:
        file_log.warning("file_complete_with_errors", **summary)
    else:
        file_log.info("file_complete", **summary)

    return summary


# -- Pipeline orchestrator -----------------------------------------------------


def run_pipeline(es: Elasticsearch) -> None:
    data_dir = Path(settings.PGN_DATA_DIR)
    pgn_files = sorted(data_dir.glob("*.pgn"))
    state = load_state()

    # Process interrupted files first -- they already have saved progress
    # so they resume rather than restart. Fresh files come after.
    pending = [p for p in pgn_files if p.name not in state["completed"]]
    interrupted = [p for p in pending if p.name in state["in_progress"]]
    fresh = [p for p in pending if p.name not in state["in_progress"]]
    ordered = interrupted + fresh

    log.info(
        "pipeline_start",
        total_files=len(pgn_files),
        completed=len(state["completed"]),
        resuming=len(interrupted),
        fresh=len(fresh),
    )

    for pgn_path in ordered:
        try:
            index_pgn_file(es, pgn_path, state)
        except Exception as exc:
            # State was already checkpointed mid-file.
            # Next run will resume from the last saved offset.
            log.error(
                "file_failed",
                file=pgn_path.name,
                error=str(exc),
                exc_info=True,
            )

    log.info("pipeline_complete", completed=len(state["completed"]))
