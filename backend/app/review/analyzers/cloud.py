import asyncio

import structlog

import chess
import requests
from berserk import TokenSession
from berserk.clients import Analysis
from berserk.exceptions import BerserkError

from app.review.analyzers.base import GameAnalyzer
from app.review.schemas import AnalysisResult, AnalysisScore

log = structlog.get_logger()


class CloudAnalyzer(GameAnalyzer):
    def __init__(self):
        self.client = Analysis(TokenSession(""))

    async def analyze(
        self, board: chess.Board, root_moves: list[chess.Move] | None = None
    ) -> AnalysisResult | None:
        if root_moves:
            log.debug("review_cloud_skip_root_moves")
            return None

        try:
            evaluation = await asyncio.wait_for(
                asyncio.to_thread(self.client.get_cloud_evaluation, board.fen()),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            log.debug("review_cloud_timeout")
            return None
        except (BerserkError, requests.RequestException):
            log.debug("review_cloud_miss")
            return None

        pv = (evaluation.get("pvs") or [None])[0]
        if not pv:
            log.debug("review_cloud_missing_pv")
            return None

        log.info("review_cloud_hit", depth=evaluation.get("depth"))
        cp = pv.get("cp")
        mate = pv.get("mate")
        if board.turn == chess.BLACK:
            cp = -cp if cp is not None else None
            mate = -mate if mate is not None else None

        moves = pv.get("moves", "").split()
        return AnalysisResult(
            source="lichess_cloud",
            depth=evaluation.get("depth", 0),
            score=AnalysisScore(cp=cp, mate=mate),
            score_value=self._score_value(cp, mate),
            best_move_uci=moves[0] if moves else None,
        )

    def _score_value(self, cp: int | None, mate: int | None) -> int | None:
        if mate is None:
            return cp
        sign = 1 if mate > 0 else -1
        return sign * (1_000_000 - abs(mate))
