"""
app/review/service.py

Opening review service.
"""

import chess
import structlog
from collections import Counter
from typing import Any
from chess.pgn import Game
from app.config import settings
from app.review.schemas import AnalysisResult
from app.review.analyzers.chain import AnalysisChain
from app.review.analyzers.cloud import CloudAnalyzer
from app.review.analyzers.local import LocalAnalyzer
from motor.motor_asyncio import AsyncIOMotorDatabase


log = structlog.get_logger()


class AnalyzerService:
    """
    Handles caching, calling the analyzer chain, logging.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.max_plies = settings.OPENING_REVIEW_MAX_PLIES
        self.analyzer_chain = AnalysisChain(
            [CloudAnalyzer(), LocalAnalyzer(depth=settings.OPENING_REVIEW_ENGINE_DEPTH)]
        )
        self.db = db
        self.analysis_counts = {
            "cache_hits": 0,
            "cache_misses": 0,
            "no_result": 0,
            "by_source": {"lichess_cloud": 0, "local_stockfish": 0},
        }
        log.info("review_analyzer_service_initialized", max_plies=self.max_plies)

    def _normalize_fen(self, board: chess.Board) -> str:
        return " ".join(board.fen().split(" ")[:4])

    async def analyze(
        self, board: chess.Board
    ) -> AnalysisResult | None:
        fen = self._normalize_fen(board)
        # root_key = ",".join(move.uci() for move in root_moves or [])
        cache_key = fen
        cached = await self.db.position_evals.find_one({"_id": cache_key})
        if cached:
            self.analysis_counts["cache_hits"] += 1
            log.debug("review_analysis_cache_hit", fen=fen)
            return AnalysisResult(**cached["result"])
        self.analysis_counts["cache_misses"] += 1
        log.debug("review_analysis_cache_miss", fen=fen)
        result = await self.analyzer_chain.analyze(
            board
        )
        if result:
            await self.db.position_evals.replace_one(
                {"_id": cache_key},
                {"result": result.model_dump()},
                upsert=True
            )
            self.analysis_counts["by_source"][result.source] += 1
            log.info(
                "review_analysis_complete",
                source=result.source,
                fen=fen,
                best_move=result.best_move_uci,
            )
        else:
            self.analysis_counts["no_result"] += 1
            log.warning("review_analysis_no_result", fen=fen)
        return result

    async def analyze_game(self, game: Game | None, player: str) -> dict[str, Any] | None:
        if game is None:
            log.warning("review_game_missing")
            return None
        white = game.headers.get("White", "?")
        black = game.headers.get("Black", "?")
        result = game.headers.get("Result", "*")
        log.info("review_game_started", player=player, white=white, black=black, result=result)
        player_color = None
        if white == player:
            player_color = chess.WHITE
        if black == player:
            player_color = chess.BLACK
        if player_color is None:
            log.info("review_game_skipped_player_not_found", player=player, white=white, black=black)
            return None

        buckets: dict[str, dict[str, Any]] = {}
        board = game.board()
        node = game
        ply = 0

        # For each FEN, store the different moves played by the player there and the best move.
        # On the frontend we will allow setting up the board -> search by FEN, show different moves played, and win rate at each FEN
        while node.variations and ply < self.max_plies:
            next_node = node.variation(0)
            move = next_node.move

            fen = self._normalize_fen(board)
            bucket = buckets.setdefault(
                fen,
                {
                    "fen": fen,
                    "side_to_move": "white" if board.turn == chess.WHITE else "black",
                    "occurrences": 0,
                    "wins": 0,
                        "draws": 0,
                    "played_moves": Counter(),
                    "best_move": {}
                },
            )
            bucket["occurrences"] += 1
            if (result == "1-0" and player_color == chess.WHITE) or (result == "0-1" and player_color == chess.BLACK):
                bucket["wins"] += 1
            if result == "1/2-1/2":
                bucket["draws"] += 1
            bucket["played_moves"][move.uci()] = bucket["played_moves"].get(move.uci(), 0) + 1
            if board.turn == player_color and bucket["best_move"] == {}:
                best_move_analysis = await self.analyze(board=board)
                if best_move_analysis is None:
                    log.error("review_analysis_failed", fen=fen)
                    continue
                bucket["best_move"] = best_move_analysis.best_move_uci


            board.push(move)
            node = next_node
            ply += 1

        log.info(
            "review_game_bucketed",
            player=player,
            positions_seen=sum(bucket["occurrences"] for bucket in buckets.values()),
            unique_positions=len(buckets),
        )
        return {
            "color": "white" if player_color == chess.WHITE else "black",
            "buckets": buckets
        }
