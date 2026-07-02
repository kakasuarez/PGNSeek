import chess

from app.review.analyzers.base import GameAnalyzer
from app.review.schemas import AnalysisResult


class CloudAnalyzer(GameAnalyzer):
    async def analyze(
        self, board: chess.Board, root_moves: list[chess.Move] | None = None
    ) -> AnalysisResult | None:
        return None
