"""
app/ingestion/pipeline.py

PGN ingestion pipeline. CLI entry point: pipeline/ingest.py

Responsibilities:
  1. Find all PGN files in PGN_DATA_DIR
  2. Skip files already processed (resumable via ingestion_state.json)
  3. For each file: parse games → compute features → bulk index to ES

Design decisions:
  - game_hash used as ES _id -> reingestion is idempotent
  - Synchronous (no Celery) for MVP
  - Batch size controlled by ES_BULK_BATCH_SIZE env var
  - Games before MIN_YEAR are skipped at parse time
"""

import json
import hashlib
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
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}


# ── Game hash ─────────────────────────────────────────────────────────────────

def compute_game_hash(game: chess.pgn.Game) -> str:
    h = game.headers
    moves = " ".join(str(m) for m in game.mainline_moves())
    canonical = (
        f"{h.get('White','')}|{h.get('Black','')}|"
        f"{h.get('Date','')}|{moves}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


# ── Feature extraction ────────────────────────────────────────────────────────

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
    if (board.pieces(chess.BISHOP, chess.WHITE) or board.pieces(chess.BISHOP, chess.BLACK)
            or board.pieces(chess.KNIGHT, chess.WHITE) or board.pieces(chess.KNIGHT, chess.BLACK)):
        return "minor_piece"
    return "pawn"


def compute_features(game: chess.pgn.Game) -> dict:
    board = game.board()
    balances: list[float] = []
    pawn_captures = 0
    endgame_move = -1
    endgame_type = "none"

    # ENDGAME THRESHOLD: both sides at or below 13 non-king points.
    # 13 covers: Q alone (9), R+minor (8), R+2P (7), etc.
    # This correctly classifies queen endgames, rook endgames, pawn endgames.
    # The old "queens gone + piece count <= 12" was wrong on both counts.
    ENDGAME_MATERIAL_THRESHOLD = 13

    for move_num, move in enumerate(game.mainline_moves(), start=1):
        if board.is_capture(move) and board.piece_type_at(move.from_square) == chess.PAWN:
            pawn_captures += 1

        board.push(move)
        bal = material_balance(board)
        balances.append(bal)

        if endgame_move == -1:
            w_mat = side_material(board, chess.WHITE)
            b_mat = side_material(board, chess.BLACK)
            if w_mat <= ENDGAME_MATERIAL_THRESHOLD and b_mat <= ENDGAME_MATERIAL_THRESHOLD:
                endgame_move = move_num
                endgame_type = classify_endgame_type(board)

    # -- Sacrifice detection ---------------------------------------------------
    # Fix: after any large swing, check whether the balance RECOVERED
    # to near its pre-swing level within RECOVERY_WINDOW moves.
    # Recovery = trade. No recovery = genuine sacrifice.
    sacrifices = 0
    SAC_DELTA = float(settings.SACRIFICE_DELTA)   # default 3.0 -- knight/bishop threshold
    RECOVERY_WINDOW = 2                            # half-moves to wait for recapture
    RECOVERY_TOLERANCE = 1.0                       # a pawn of slippage is noise

    for i in range(len(balances) - 1):
        pre_swing_bal = balances[i - 1] if i > 0 else 0.0
        immediate_swing = abs(balances[i] - pre_swing_bal)

        if immediate_swing < SAC_DELTA:
            continue  # not a significant material event

        future_idx = min(i + RECOVERY_WINDOW, len(balances) - 1)
        future_bal = balances[future_idx]

        # Did balance return to within RECOVERY_TOLERANCE of pre-capture level?
        recovered = abs(future_bal - pre_swing_bal) <= RECOVERY_TOLERANCE
        if not recovered:
            sacrifices += 1

    swings = [abs(balances[i] - balances[i - 1]) for i in range(1, len(balances))]
    avg_swing = sum(swings) / len(swings) if swings else 0.0
    max_swing = max(swings, default=0.0)

    return {
        "num_moves":              len(balances),
        "avg_material_swings":    round(avg_swing, 3),
        "max_material_swing":     round(max_swing, 3),
        "piece_sacrifices":       sacrifices,
        "entered_endgame":        endgame_move > 0,
        "endgame_move":           endgame_move,
        "endgame_type":           endgame_type,
        "pawn_structure_changes": pawn_captures,
    }


# ── Document builder ──────────────────────────────────────────────────────────

def game_to_document(game: chess.pgn.Game, source_file: str) -> dict | None:
    h = game.headers
    game_hash = compute_game_hash(game)

    # Year filter
    date_str = h.get("Date", "")
    try:
        year = int(date_str[:4])
    except (ValueError, TypeError):
        year = None

    if year and year < settings.MIN_YEAR:
        return None  # skip pre-2010 games

    try:
        white_elo = int(h.get("WhiteElo", 0)) or None
        black_elo = int(h.get("BlackElo", 0)) or None
    except ValueError:
        white_elo = black_elo = None

    avg_rating = (
        (white_elo + black_elo) / 2
        if white_elo and black_elo else None
    )

    eco = h.get("ECO", None)
    eco_prefix = eco[0] if eco else None
    features = compute_features(game)

    return {
        "game_hash":    game_hash,
        "white":        h.get("White", "?"),
        "black":        h.get("Black", "?"),
        "white_elo":    white_elo,
        "black_elo":    black_elo,
        "avg_rating":   avg_rating,
        "result":       h.get("Result", None),
        "date":         date_str if date_str != "????.??.??" else None,
        "year":         year,
        "eco":          eco,
        "eco_prefix":   eco_prefix,
        "opening_name": h.get("Opening", None),
        "event":        h.get("Event", None),
        "site":         h.get("Site", None),
        "source_file":  source_file,
        **features,
    }


# -- Bulk indexing -------------------------------------------------------------

def iter_bulk_actions(documents: list[dict]) -> Generator[dict, None, None]:
    for doc in documents:
        yield {
            "_index": ALIAS_NAME,
            "_id":    doc["game_hash"],
            "_source": doc,
        }


def index_pgn_file(es: Elasticsearch, pgn_path: Path) -> dict:
    """
    Parse one PGN file and bulk-index all valid games.
    Returns a summary dict with counts.
    """
    log.info("indexing_file", path=str(pgn_path))
    parsed = indexed = skipped = errors = 0
    batch: list[dict] = []

    with open(pgn_path, encoding="utf-8", errors="replace") as f:
        while True:
            try:
                game = chess.pgn.read_game(f)
            except Exception as exc:
                log.warning("pgn_parse_error", file=str(pgn_path), error=str(exc))
                errors += 1
                continue

            if game is None:
                break

            parsed += 1
            doc = game_to_document(game, source_file=pgn_path.name)
            if doc is None:
                skipped += 1
                continue

            batch.append(doc)
            if len(batch) >= settings.ES_BULK_BATCH_SIZE:
                success, _ = bulk(es, iter_bulk_actions(batch), raise_on_error=False)
                indexed += success
                batch = []

    if batch:
        success, _ = bulk(es, iter_bulk_actions(batch), raise_on_error=False)
        indexed += success

    summary = {
        "file": pgn_path.name,
        "parsed": parsed,
        "indexed": indexed,
        "skipped_year": skipped,
        "errors": errors,
    }
    log.info("file_complete", **summary)
    return summary


# ── Resumable state ───────────────────────────────────────────────────────────

def load_state() -> set[str]:
    state_path = Path(settings.INGESTION_STATE_FILE)
    if state_path.exists():
        return set(json.loads(state_path.read_text()).get("completed", []))
    return set()


def save_state(completed: set[str]) -> None:
    state_path = Path(settings.INGESTION_STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"completed": sorted(completed)}, indent=2))


def run_pipeline(es: Elasticsearch) -> None:
    """
    Main pipeline entry. Processes all PGN files in PGN_DATA_DIR,
    skipping those already recorded in ingestion_state.json.
    """
    data_dir = Path(settings.PGN_DATA_DIR)
    pgn_files = sorted(data_dir.glob("*.pgn"))
    completed = load_state()

    log.info("pipeline_start", total_files=len(pgn_files), already_done=len(completed))

    for pgn_path in pgn_files:
        if pgn_path.name in completed:
            log.info("skipping_completed", file=pgn_path.name)
            continue
        try:
            index_pgn_file(es, pgn_path)
            completed.add(pgn_path.name)
            save_state(completed)
        except Exception as exc:
            log.error("file_failed", file=pgn_path.name, error=str(exc))
            # Continue with next file — don't abort the whole pipeline

    log.info("pipeline_complete", total_indexed=len(completed))
