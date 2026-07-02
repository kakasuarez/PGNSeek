from typing import List

import chess

from app.review.analyzers.base import GameAnalyzer
from app.review.schemas import AnalysisResult


class AnalysisChain(GameAnalyzer):
    def __init__(self, analyzers: List[GameAnalyzer]):
        self.analyzers = analyzers

    async def analyze(
        self, board: chess.Board, root_moves: list[chess.Move] | None = None
    ) -> AnalysisResult | None:
        for analyzer in self.analyzers:
            result = await analyzer.analyze(board, root_moves=root_moves)
            if result is not None:
                return result
        return None
