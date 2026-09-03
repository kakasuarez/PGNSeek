from typing import List

import chess
import structlog

from app.review.analyzers.base import GameAnalyzer
from app.review.schemas import AnalysisResult


log = structlog.get_logger()


class AnalysisChain(GameAnalyzer):
    def __init__(self, analyzers: List[GameAnalyzer]):
        self.analyzers = analyzers

    async def analyze(
        self, board: chess.Board, root_moves: list[chess.Move] | None = None
    ) -> AnalysisResult | None:
        for analyzer in self.analyzers:
            result = await analyzer.analyze(board)
            if result is not None:
                log.debug(
                    "review_analyzer_chain_hit",
                    analyzer=analyzer.__class__.__name__,
                    source=result.source,
                )
                return result
            log.debug("review_analyzer_chain_miss", analyzer=analyzer.__class__.__name__)
        return None
