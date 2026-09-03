from abc import ABC, abstractmethod

import chess

from app.review.schemas import AnalysisResult


class GameAnalyzer(ABC):
    @abstractmethod
    async def analyze(
        self, board: chess.Board
    ) -> AnalysisResult | None:
        """
        Analyze an individual position.
        """
        pass
