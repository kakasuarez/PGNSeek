#!/usr/bin/env python3

"""
Build a first-pass opening review report from a PGN file.

This version is intentionally simple:
    - synchronous only
    - no cache
    - local Stockfish only
    - deduplicates positions before analysis

The core unit is a unique pre-move position. For each normalized FEN in the
first N plies, the report stores:
    - how often that position occurred
    - which move(s) were played from that position
    - one local Stockfish evaluation for the position

Examples:
    backend/venv/bin/python scripts/opening_position_report.py \
        --input "data/pgn/export/lichess export white analysis.pgn" \
        --player game \
        --engine-path /path/to/stockfish
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_backend = Path(__file__).parent.parent / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

import chess
import chess.engine
import chess.pgn

from app.config import settings


def normalize_fen(board: chess.Board) -> str:
    ep_square = (
        chess.square_name(board.ep_square) if board.ep_square is not None else "-"
    )
    return " ".join(
        [
            board.board_fen(),
            "w" if board.turn == chess.WHITE else "b",
            board.castling_xfen(),
            ep_square,
        ]
    )


def score_to_dict(score: chess.engine.Score | None) -> dict[str, int | None]:
    if score is None:
        return {}
    if score.is_mate():
        return {"cp": None, "mate": score.mate()}
    return {"cp": score.score(), "mate": None}


def score_to_ordering_value(
    pov_score: chess.engine.PovScore | None,
    perspective: chess.Color,
) -> int | None:
    if pov_score is None:
        return None

    score = pov_score.pov(perspective)
    if score.is_mate():
        mate = score.mate()
        if mate is None:
            return None
        sign = 1 if mate > 0 else -1
        return sign * (1_000_000 - abs(mate))

    cp = score.score()
    return cp if cp is not None else None


def analyze_position(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    depth: int,
    root_moves: list[chess.Move] | None = None,
) -> dict[str, Any]:
    info = engine.analyse(
        board,
        chess.engine.Limit(depth=depth),
        root_moves=root_moves,
    )
    pv = info.get("pv", [])
    best_move = pv[0] if pv else None
    perspective = board.turn
    pov_score = info.get("score")

    return {
        "source": "local_stockfish",
        "depth": depth,
        "score": score_to_dict(pov_score.pov(perspective) if pov_score else None),
        "score_value": score_to_ordering_value(pov_score, perspective),
        "best_move_uci": best_move.uci() if best_move else None,
    }


def build_position_reports(
    engine: chess.engine.SimpleEngine,
    buckets: dict[str, dict[str, Any]],
    depth: int,
) -> list[dict[str, Any]]:
    position_reports: list[dict[str, Any]] = []

    for fen, bucket in buckets.items():
        board = chess.Board(fen)
        evaluation = analyze_position(engine, board=board, depth=depth)
        position_reports.append(
            {
                "fen": bucket["fen"],
                "side_to_move": bucket["side_to_move"],
                "occurrences": bucket["occurrences"],
                "played_moves": {
                    uci: count for uci, count in bucket["played_moves"].most_common()
                },
                "engine": evaluation,
            }
        )

    position_reports.sort(key=lambda item: (-item["occurrences"], item["fen"]))
    return position_reports


def build_mistake_reports(
    engine: chess.engine.SimpleEngine,
    position_reports: list[dict[str, Any]],
    depth: int,
) -> list[dict[str, Any]]:
    mistake_reports: list[dict[str, Any]] = []

    for position_report in position_reports:
        board = chess.Board(position_report["fen"])
        best_move_uci = position_report["engine"]["best_move_uci"]
        best_score = position_report["engine"].get("score", {})
        best_score_value = position_report["engine"].get("score_value")

        suboptimal_moves: list[dict[str, Any]] = []
        suboptimal_occurrences = 0
        for played_move_uci, count in position_report["played_moves"].items():
            if played_move_uci == best_move_uci:
                continue

            move = chess.Move.from_uci(played_move_uci)
            move_info = analyze_position(
                engine, board=board, depth=depth, root_moves=[move]
            )
            move_score = move_info.get("score", {})
            move_score_value = move_info.get("score_value")

            score_loss = None
            if best_score_value is not None and move_score_value is not None:
                score_loss = best_score_value - move_score_value

            suboptimal_occurrences += count

            suboptimal_moves.append(
                {
                    "uci": played_move_uci,
                    "count": count,
                    "score": move_score,
                    "score_loss": score_loss,
                }
            )

        if not suboptimal_moves:
            continue

        suboptimal_moves.sort(
            key=lambda item: (
                -item["count"],
                -(item["score_loss"] or -1),
                item["uci"],
            )
        )
        mistake_reports.append(
            {
                "fen": position_report["fen"],
                "side_to_move": position_report["side_to_move"],
                "occurrences": position_report["occurrences"],
                "best_move_uci": best_move_uci,
                "best_score": best_score,
                "played_moves": position_report["played_moves"],
                "suboptimal_occurrences": suboptimal_occurrences,
                "suboptimal_moves": suboptimal_moves,
            }
        )

    mistake_reports.sort(key=lambda item: (-item["occurrences"], item["fen"]))
    return mistake_reports


def build_report(
    input_path: Path,
    engine_path: str,
    player: str | None,
    max_games: int | None,
    max_plies: int,
    depth: int,
) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    positions_seen = 0
    games_scanned = 0
    games_included = 0

    with input_path.open("r", encoding="utf-8", errors="replace") as handle:
        while max_games is None or games_scanned < max_games:
            game = chess.pgn.read_game(handle)
            if game is None:
                break

            games_scanned += 1
            player_color = None
            if player:
                white = game.headers.get("White", "")
                black = game.headers.get("Black", "")
                if white == player:
                    player_color = chess.WHITE
                if black == player:
                    player_color = chess.BLACK
            if player and player_color is None:
                continue

            games_included += 1
            board = game.board()
            node = game
            ply = 0

            while node.variations and ply < max_plies:
                next_node = node.variation(0)
                move = next_node.move

                if player_color is None or board.turn == player_color:
                    fen = normalize_fen(board)
                    bucket = buckets.setdefault(
                        fen,
                        {
                            "fen": normalize_fen(board),
                            "side_to_move": (
                                "white" if board.turn == chess.WHITE else "black"
                            ),
                            "occurrences": 0,
                            "played_moves": Counter(),
                        },
                    )
                    bucket["occurrences"] += 1
                    bucket["played_moves"][move.uci()] += 1
                    positions_seen += 1

                board.push(move)
                node = next_node
                ply += 1

    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    try:
        position_reports = build_position_reports(
            engine=engine, buckets=buckets, depth=depth
        )
        mistake_reports = build_mistake_reports(
            engine=engine,
            position_reports=position_reports,
            depth=depth,
        )
    finally:
        engine.quit()

    return {
        "report_type": "opening_position_report_v1",
        "input": {
            "pgn_file": str(input_path),
            "player": player,
            "max_games": max_games,
            "max_plies": max_plies,
            "engine_path": engine_path,
            "engine_depth": depth,
        },
        "summary": {
            "games_scanned": games_scanned,
            "games_included": games_included,
            "positions_seen": positions_seen,
            "unique_positions": len(position_reports),
            "positions_with_suboptimal_moves": len(mistake_reports),
        },
        "positions": position_reports,
        "mistakes": mistake_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deduplicated opening-position report from PGN using local Stockfish."
    )
    parser.add_argument("--input", required=True, help="Path to input PGN file")
    parser.add_argument(
        "--player",
        default=None,
        help="Username to analyze. If set, only positions where that player is to move are included.",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Maximum number of games to scan",
    )
    parser.add_argument(
        "--max-plies",
        type=int,
        default=20,
        help="Only inspect positions from the first N plies of each game",
    )
    parser.add_argument(
        "--engine-path",
        default=settings.STOCKFISH_PATH,
        help="Path to local Stockfish binary. Defaults to STOCKFISH_PATH.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=settings.OPENING_REVIEW_ENGINE_DEPTH,
        help="Stockfish depth for each unique position",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path. Defaults to stdout.",
    )
    args = parser.parse_args()

    if not args.engine_path:
        raise SystemExit(
            "Stockfish path is required. Pass --engine-path or set STOCKFISH_PATH in .env."
        )

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input PGN does not exist: {input_path}")

    report = build_report(
        input_path=input_path,
        engine_path=args.engine_path,
        player=args.player,
        max_games=args.max_games,
        max_plies=args.max_plies,
        depth=args.depth,
    )

    payload = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
