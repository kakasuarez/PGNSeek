#!/usr/bin/env python3
"""
PGN Parser for Chess Game Retrieval Engine

Streams through large PGN files efficiently, extracts metadata and moves,
and outputs JSONL format for downstream processing.
"""

import json
import sys
from typing import Optional, Dict, Any
from pathlib import Path
import chess.pgn
from tqdm import tqdm


def extract_game_data(game: chess.pgn.Game) -> Optional[Dict[str, Any]]:
    """
    Extract relevant data from a chess game.

    Args:
        game: A chess.pgn.Game object

    Returns:
        Dictionary with game metadata and moves, or None if invalid
    """
    try:
        headers = game.headers

        # Extract basic metadata
        white = headers.get("White", "Unknown")
        black = headers.get("Black", "Unknown")
        result = headers.get("Result", "*")
        eco = headers.get("ECO", "")
        opening = headers.get("Opening", "")
        event = headers.get("Event", "")
        site = headers.get("Site", "")
        date = headers.get("Date", "")
        round_num = headers.get("Round", "")
        white_elo = headers.get("WhiteElo", "")
        black_elo = headers.get("BlackElo", "")

        # Get PGN text (without move tree, just headers + moves as string)
        pgn_exporter = chess.pgn.StringExporter(
            headers=True, variations=False, comments=False
        )
        pgn_text = game.accept(pgn_exporter)

        # Extract UCI moves
        board = game.board()
        uci_moves = []
        for move in game.mainline_moves():
            uci_moves.append(move.uci())
            board.push(move)

        # Generate embedding text: a rich textual representation
        # Combine key information that would be useful for semantic search
        embedding_parts = []

        if opening:
            embedding_parts.append(f"Opening: {opening}")
        if eco:
            embedding_parts.append(f"ECO code: {eco}")

        embedding_parts.append(f"White: {white}")
        embedding_parts.append(f"Black: {black}")

        if white_elo:
            embedding_parts.append(f"White rating: {white_elo}")
        if black_elo:
            embedding_parts.append(f"Black rating: {black_elo}")

        if event:
            embedding_parts.append(f"Event: {event}")
        if site:
            embedding_parts.append(f"Site: {site}")
        if date:
            embedding_parts.append(f"Date: {date}")

        result_text = {
            "1-0": "White won",
            "0-1": "Black won",
            "1/2-1/2": "Draw",
            "*": "Unfinished",
        }.get(result, result)
        embedding_parts.append(f"Result: {result_text}")

        # Add move count for context
        embedding_parts.append(f"Number of moves: {len(uci_moves)}")

        # Create a natural language description
        embedding_text = ". ".join(embedding_parts) + "."

        game_data = {
            "white": white,
            "black": black,
            "result": result,
            "eco": eco,
            "opening": opening,
            "event": event,
            "site": site,
            "date": date,
            "round": round_num,
            "white_elo": white_elo,
            "black_elo": black_elo,
            "pgn": pgn_text,
            "uci_moves": uci_moves,
            "embedding_text": embedding_text,
        }

        return game_data

    except Exception as e:
        print(f"Error processing game: {e}", file=sys.stderr)
        return None


def parse_pgn_file(input_path: str, output_path: str, max_games: Optional[int] = None):
    """
    Parse a PGN file and output JSONL format.

    Args:
        input_path: Path to input PGN file
        output_path: Path to output JSONL file
        max_games: Maximum number of games to process (None for all)
    """
    input_file = Path(input_path)
    output_file = Path(output_path)

    if not input_file.exists():
        print(f"Error: Input file '{input_path}' not found", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing PGN file: {input_path}")
    print(f"Output will be written to: {output_path}")

    games_processed = 0
    games_written = 0
    games_skipped = 0

    with open(input_file, "r", encoding="utf-8", errors="ignore") as pgn_file, open(
        output_file, "w", encoding="utf-8"
    ) as jsonl_file:

        # Use tqdm for progress bar
        with tqdm(desc="Processing games", unit=" games") as pbar:
            while True:
                # Check if we've reached the max games limit
                if max_games and games_processed >= max_games:
                    break

                # Read next game
                game = chess.pgn.read_game(pgn_file)
                if game is None:
                    break

                games_processed += 1

                # Extract game data
                game_data = extract_game_data(game)

                if game_data:
                    # Write as JSON line
                    json.dump(game_data, jsonl_file, ensure_ascii=False)
                    jsonl_file.write("\n")
                    games_written += 1
                else:
                    games_skipped += 1

                pbar.update(1)

                # Periodic status update
                if games_processed % 1000 == 0:
                    pbar.set_postfix(
                        {"written": games_written, "skipped": games_skipped}
                    )

    print(f"\n✓ Parsing complete!")
    print(f"  Total games processed: {games_processed}")
    print(f"  Games written: {games_written}")
    print(f"  Games skipped: {games_skipped}")
    print(f"  Output file: {output_path}")
    print(f"  Output file size: {output_file.stat().st_size / (1024**2):.2f} MB")


def main():
    """Main entry point for the script."""
    if len(sys.argv) < 3:
        print("Usage: python parse_pgn.py <input.pgn> <output.jsonl> [max_games]")
        print("\nExample:")
        print("  python parse_pgn.py lichess_db_broadcast_2025-10.pgn games.jsonl")
        print(
            "  python parse_pgn.py lichess_db_broadcast_2025-10.pgn games.jsonl 10000"
        )
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    max_games = int(sys.argv[3]) if len(sys.argv) > 3 else None

    if max_games:
        print(f"Processing up to {max_games} games...")

    parse_pgn_file(input_path, output_path, max_games)


if __name__ == "__main__":
    main()
