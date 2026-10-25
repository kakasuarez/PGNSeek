"""
app/review/service.py

Opening review service.
"""

import chess
import structlog
from datetime import datetime
from typing import Any, Iterable
from chess.pgn import Game
from app.config import settings
from app.review.schemas import AnalysisResult, AnalysisScore
from app.review.report import ReviewReportBuilder, normalize_fen, score_move
from app.review.store import save_positions
from app.review.analyzers.chain import AnalysisChain
from app.review.analyzers.cloud import CloudAnalyzer
from app.review.analyzers.local import LocalAnalyzer
from motor.motor_asyncio import AsyncIOMotorDatabase


log = structlog.get_logger()


class AnalyzerService:
    """
    Handles caching, calling the analyzer chain, logging, and building the review report.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.max_plies = settings.OPENING_REVIEW_MAX_PLIES
        self.local_analyzer = LocalAnalyzer(depth=settings.OPENING_REVIEW_ENGINE_DEPTH)
        self.analyzer_chain = AnalysisChain([CloudAnalyzer(), self.local_analyzer])
        self.db = db
        self.analysis_counts = {
            "cache_hits": 0,
            "cache_misses": 0,
            "no_result": 0,
            "by_source": {"lichess_cloud": 0, "local_stockfish": 0},
        }
        log.info("review_analyzer_service_initialized", max_plies=self.max_plies)

    def close(self) -> None:
        """Stop the local Stockfish process, if one was started."""
        self.local_analyzer.close()

    async def analyze(
        self, board: chess.Board
    ) -> AnalysisResult | None:
        fen = normalize_fen(board)
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

    async def review(
        self,
        games: Iterable[Game | None],
        player: str,
        tree_id: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        """
        Build the opening review for `player` from their games.

        Saves the position tree under `tree_id` and returns the report
        (summary and ranked mistakes) to store on the job.
        """
        builder = ReviewReportBuilder(player, self.max_plies)
        for game in games:
            if game is None:
                continue
            if not builder.add_game(game):
                log.info(
                    "review_game_skipped",
                    player=player,
                    white=game.headers.get("White", "?"),
                    black=game.headers.get("Black", "?"),
                )

        # Each unique position is evaluated once, after all games are collected
        for position in builder.player_positions():
            board = chess.Board(position["fen"])
            best = await self.analyze(board)
            if best is None:
                log.error("review_analysis_failed", fen=position["fen"])
                continue
            builder.set_evaluation(position, best)

            for uci, played in position["played_moves"].items():
                after_move = None
                if uci != best.best_move_uci:
                    after_move = await self._evaluate_after(board, chess.Move.from_uci(uci))
                    if after_move is None:
                        log.error("review_move_analysis_failed", fen=position["fen"], move=uci)
                        continue
                played.update(score_move(best.score, after_move))

        report = builder.finish()
        saved = await save_positions(self.db, tree_id, builder.positions(), expires_at)
        log.info(
            "review_report_built",
            player=player,
            tree_id=tree_id,
            positions_saved=saved,
            games_included=builder.games_included,
            games_skipped=builder.games_skipped,
            counts={color: r["counts"] for color, r in report["repertoires"].items()},
            analysis_counts=self.analysis_counts,
        )
        return report

    async def _evaluate_after(self, board: chess.Board, move: chess.Move) -> AnalysisScore | None:
        """Evaluate the position after `move`, from the opponent's (side to move's) point of view."""
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            return AnalysisScore(mate=0)
        if after.is_game_over():
            return AnalysisScore(cp=0)
        analysis = await self.analyze(after)
        return analysis.score if analysis else None
