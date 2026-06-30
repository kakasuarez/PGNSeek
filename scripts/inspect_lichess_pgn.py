#!/usr/bin/env python3

"""
Inspect a PGN export and print the metadata available at game and move level.

This is aimed at Lichess exports, especially when optional exporter features
such as engine analysis, move times, opening tags, and textual annotations are
enabled.

Examples:
    python scripts/inspect_lichess_pgn.py \
        --input "data/pgn/export/lichess export white analysis.pgn"

    python scripts/inspect_lichess_pgn.py \
        --input "data/pgn/export/lichess export white analysis.pgn" \
        --max-games 2 --max-moves 12
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import chess
import chess.pgn


OPENING_COMMENT_RE = re.compile(r"\b[A-E][0-9]{2}\s+")


def format_score(score: chess.engine.Score | None) -> str | None:
    if score is None:
        return None
    if score.is_mate():
        mate = score.mate()
        return f"mate {mate}"
    cp = score.white().score()
    return f"cp {cp}"


def classify_comment(comment: str) -> list[str]:
    labels: list[str] = []
    if not comment:
        return labels
    if "[%eval" in comment:
        labels.append("eval_tag")
    if "[%clk" in comment:
        labels.append("clock_tag")
    if "[%emt" in comment:
        labels.append("elapsed_move_time_tag")
    if OPENING_COMMENT_RE.search(comment.strip()):
        labels.append("opening_comment")
    if "best." in comment or "Blunder." in comment or "Mistake." in comment or "Inaccuracy." in comment:
        labels.append("engine_annotation_text")
    if comment.strip() and not labels:
        labels.append("plain_text_comment")
    return labels


def inspect_game(game: chess.pgn.Game, game_number: int, max_moves: int | None) -> dict[str, int]:
    feature_counts: Counter[str] = Counter()

    print(f"\n=== Game {game_number} ===")
    print("Headers:")
    for key, value in game.headers.items():
        print(f"  {key}: {value}")

    board = game.board()
    node = game
    move_number = 0

    print("Moves:")
    while node.variations:
        next_node = node.variation(0)
        move_number += 1
        move = next_node.move
        san = board.san(move)
        color = "white" if board.turn == chess.WHITE else "black"
        fullmove = board.fullmove_number
        fen_before = board.fen()

        board.push(move)
        fen_after = board.fen()

        raw_comment = next_node.comment or ""
        starting_comment = next_node.starting_comment or ""
        nags = sorted(next_node.nags)
        eval_score = None
        clock = None
        emt = None

        try:
            eval_score = next_node.eval()
        except Exception:
            eval_score = None

        try:
            clock = next_node.clock()
        except Exception:
            clock = None

        try:
            emt = next_node.emt()
        except Exception:
            emt = None

        variation_sans: list[str] = []
        for side_variation in next_node.variations[1:]:
            variation_sans.append(next_node.board().variation_san([side_variation.move]))

        comment_labels = classify_comment(raw_comment)
        for label in comment_labels:
            feature_counts[label] += 1
        if eval_score is not None:
            feature_counts["parsed_eval"] += 1
        if clock is not None:
            feature_counts["parsed_clock"] += 1
        if emt is not None:
            feature_counts["parsed_elapsed_move_time"] += 1
        if nags:
            feature_counts["nags"] += 1
        if variation_sans:
            feature_counts["side_variations"] += 1
        if starting_comment:
            feature_counts["starting_comment"] += 1

        print(f"  Ply {move_number}: {fullmove}.{color[0]} {san}")
        print(f"    UCI: {move.uci()}")
        print(f"    FEN before: {fen_before}")
        print(f"    FEN after:  {fen_after}")
        if nags:
            print(f"    NAGs: {nags}")
        if eval_score is not None:
            print(f"    Eval: {format_score(eval_score)}")
        if clock is not None:
            print(f"    Clock: {clock:.1f}s")
        if emt is not None:
            print(f"    Elapsed move time: {emt:.1f}s")
        if raw_comment:
            print(f"    Comment: {raw_comment}")
        if starting_comment:
            print(f"    Starting comment: {starting_comment}")
        if comment_labels:
            print(f"    Comment labels: {', '.join(comment_labels)}")
        if variation_sans:
            print(f"    Side variations: {variation_sans}")

        node = next_node
        if max_moves is not None and move_number >= max_moves:
            break

    return dict(feature_counts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect PGN game and move metadata, especially Lichess exports."
    )
    parser.add_argument("--input", required=True, help="Path to the PGN file")
    parser.add_argument(
        "--max-games",
        type=int,
        default=1,
        help="Maximum number of games to inspect",
    )
    parser.add_argument(
        "--max-moves",
        type=int,
        default=None,
        help="Maximum number of half-moves to print per game",
    )
    args = parser.parse_args()

    pgn_path = Path(args.input)
    if not pgn_path.exists():
        raise SystemExit(f"Input PGN does not exist: {pgn_path}")

    aggregate_features: Counter[str] = Counter()
    games_read = 0

    with pgn_path.open("r", encoding="utf-8", errors="replace") as handle:
        while games_read < args.max_games:
            game = chess.pgn.read_game(handle)
            if game is None:
                break
            games_read += 1
            aggregate_features.update(
                inspect_game(game, game_number=games_read, max_moves=args.max_moves)
            )

    print("\n=== File Summary ===")
    print(f"Games inspected: {games_read}")
    if aggregate_features:
        print("Features detected:")
        for key, count in sorted(aggregate_features.items()):
            print(f"  {key}: {count}")
    else:
        print("No move-level metadata features detected in inspected games.")


if __name__ == "__main__":
    main()
