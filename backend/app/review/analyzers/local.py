import asyncio

import structlog

import chess
import chess.engine

from app.config import settings
from app.review.analyzers.base import GameAnalyzer
from app.review.schemas import AnalysisResult, AnalysisScore

log = structlog.get_logger()


class LocalAnalyzer(GameAnalyzer):
    def __init__(self, depth: int, engine_path: str | None = settings.STOCKFISH_PATH):
        self.depth = depth
        self.engine_path = engine_path
        self._engine: chess.engine.SimpleEngine | None = None

    def _start_engine(self) -> chess.engine.SimpleEngine | None:
        if not self.engine_path:
            log.warning("review_local_no_engine_path")
            return None
        if self._engine is None:
            log.info("review_local_engine_start", path=self.engine_path)
            self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
        return self._engine

    def _score_to_result(self, score: chess.engine.Score | None) -> AnalysisScore:
        if score is None:
            return AnalysisScore()
        if score.is_mate():
            return AnalysisScore(cp=None, mate=score.mate())
        return AnalysisScore(cp=score.score(), mate=None)

    def _score_to_ordering_value(
        self, pov_score: chess.engine.PovScore | None, perspective: chess.Color
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

        return score.score()

    async def analyze(
        self, board: chess.Board, root_moves: list[chess.Move] | None = None
    ) -> AnalysisResult | None:
        engine = self._start_engine()
        if engine is None:
            return None

        log.debug(
            "review_local_analysis",
            fen=board.fen(),
            depth=self.depth,
            root_moves=[m.uci() for m in root_moves] if root_moves else None,
        )
        info = await asyncio.to_thread(
            engine.analyse,
            board,
            chess.engine.Limit(depth=self.depth, time=60.0),
            root_moves=root_moves,
        )
        pv = info.get("pv", [])
        best_move = pv[0] if pv else None
        perspective = board.turn
        pov_score = info.get("score")

        return AnalysisResult(
            source="local_stockfish",
            depth=self.depth,
            score=self._score_to_result(pov_score.pov(perspective) if pov_score else None),
            score_value=self._score_to_ordering_value(pov_score, perspective),
            best_move_uci=best_move.uci() if best_move else None,
        )
