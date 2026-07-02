"""
app/review/service.py

Opening review service.
"""

import chess
from collections import Counter
from typing import Any
from chess.pgn import Game
from app.config import settings
from app.review.schemas import AnalysisResult
from app.review.analyzers.chain import AnalysisChain
from app.review.analyzers.cloud import CloudAnalyzer
from app.review.analyzers.local import LocalAnalyzer

# def process_review(job: ReviewJob):
#     source: ReviewSource = create_source(job)
#     for game in source.iter_games():
#         if not game:
#             break
#         # TODO: Review `game` here.


class AnalyzerService:
    """
    Handles caching, calling the analyzer chain, logging.
    """

    def __init__(self):
        self.max_plies = settings.OPENING_REVIEW_MAX_PLIES
        self.analyzer_chain = AnalysisChain(
            [CloudAnalyzer(), LocalAnalyzer(depth=settings.OPENING_REVIEW_ENGINE_DEPTH)]
        )
        self.cache = dict()

    def _normalize_fen(self, board: chess.Board) -> str:
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

    async def analyze(
        self, board: chess.Board, root_moves: list[chess.Move] | None = None
    ) -> AnalysisResult | None:
        fen = self._normalize_fen(board)
        root_key = ",".join(move.uci() for move in root_moves or [])
        cache_key = f"{fen}|{root_key}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        self.cache[cache_key] = await self.analyzer_chain.analyze(
            board, root_moves=root_moves
        )
        return self.cache.get(cache_key)

    async def analyze_game(self, game: Game | None, player: str) -> dict[str, Any] | None:
        if game is None:
            return None
        white = game.headers.get("White", "")
        black = game.headers.get("Black", "")
        player_color = None
        if white == player:
            player_color = chess.WHITE
        if black == player:
            player_color = chess.BLACK
        if player_color is None:
            return None

        buckets: dict[str, dict[str, Any]] = {}
        board = game.board()
        node = game
        ply = 0

        while node.variations and ply < self.max_plies:
            next_node = node.variation(0)
            move = next_node.move

            if board.turn == player_color:
                fen = self._normalize_fen(board)
                bucket = buckets.setdefault(
                    fen,
                    {
                        "fen": fen,
                        "side_to_move": "white" if board.turn == chess.WHITE else "black",
                        "occurrences": 0,
                        "played_moves": Counter(),
                    },
                )
                bucket["occurrences"] += 1
                bucket["played_moves"][move.uci()] += 1

            board.push(move)
            node = next_node
            ply += 1

        positions: list[dict[str, Any]] = []
        for fen, bucket in buckets.items():
            result = await self.analyze(chess.Board(fen))
            positions.append(
                {
                    "fen": bucket["fen"],
                    "side_to_move": bucket["side_to_move"],
                    "occurrences": bucket["occurrences"],
                    "played_moves": dict(bucket["played_moves"].most_common()),
                    "engine": result.model_dump() if result else None,
                }
            )

        positions.sort(key=lambda item: (-item["occurrences"], item["fen"]))

        mistakes: list[dict[str, Any]] = []
        for position in positions:
            engine = position["engine"]
            if not engine:
                continue

            board = chess.Board(position["fen"])
            best_move_uci = engine["best_move_uci"]
            best_score_value = engine["score_value"]
            suboptimal_moves = []
            suboptimal_occurrences = 0

            for played_move_uci, count in position["played_moves"].items():
                if played_move_uci == best_move_uci:
                    continue

                move = chess.Move.from_uci(played_move_uci)
                move_result = await self.analyze(board, root_moves=[move])
                if not move_result:
                    continue

                score_loss = None
                if best_score_value is not None and move_result.score_value is not None:
                    score_loss = best_score_value - move_result.score_value

                suboptimal_occurrences += count
                suboptimal_moves.append(
                    {
                        "uci": played_move_uci,
                        "count": count,
                        "score": move_result.score.model_dump(),
                        "score_loss": score_loss,
                    }
                )

            if not suboptimal_moves:
                continue

            suboptimal_moves.sort(
                key=lambda item: (-item["count"], -(item["score_loss"] or -1), item["uci"])
            )
            mistakes.append(
                {
                    "fen": position["fen"],
                    "side_to_move": position["side_to_move"],
                    "occurrences": position["occurrences"],
                    "best_move_uci": best_move_uci,
                    "best_score": engine["score"],
                    "played_moves": position["played_moves"],
                    "suboptimal_occurrences": suboptimal_occurrences,
                    "suboptimal_moves": suboptimal_moves,
                }
            )

        mistakes.sort(key=lambda item: (-item["occurrences"], item["fen"]))
        return {
            "summary": {
                "positions_seen": sum(item["occurrences"] for item in positions),
                "unique_positions": len(positions),
                "positions_with_suboptimal_moves": len(mistakes),
            },
            "positions": positions,
            "mistakes": mistakes,
        }
