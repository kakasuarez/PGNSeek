"""
Tests for opening review mistake detection.

Run from backend/: .venv/bin/python -m pytest app/tests
"""

import asyncio
import io

import chess
import chess.pgn
import pytest

from app.review.report import (
    ReviewReportBuilder,
    classify,
    normalize_fen,
    score_move,
    score_to_cp,
    winning_chances,
)
from app.review.schemas import AnalysisResult, AnalysisScore
from app.review.service import AnalyzerService
from app.review.store import get_positions
from app.tests.fake_mongo import FakeDB


def make_game(
    moves: str,
    white: str = "me",
    black: str = "them",
    result: str = "1-0",
    fen: str | None = None,
) -> chess.pgn.Game:
    headers = f'[White "{white}"]\n[Black "{black}"]\n[Result "{result}"]\n'
    if fen:
        headers += f'[SetUp "1"]\n[FEN "{fen}"]\n'
    game = chess.pgn.read_game(io.StringIO(f"{headers}\n{moves} {result}"))
    assert game is not None
    return game


def fen_after(*uci_moves: str) -> str:
    board = chess.Board()
    for uci in uci_moves:
        board.push_uci(uci)
    return normalize_fen(board)


# -- Scoring -------------------------------------------------------------------


def test_winning_chances_is_symmetric_and_clamped():
    assert winning_chances(0) == 0
    assert winning_chances(300) == pytest.approx(-winning_chances(-300))
    assert winning_chances(5000) == winning_chances(1000)


@pytest.mark.parametrize(
    "score, cp",
    [
        (AnalysisScore(cp=45), 45),
        (AnalysisScore(mate=1), 2000),
        (AnalysisScore(mate=3), 1800),
        (AnalysisScore(mate=15), 1100),  # mates beyond 10 moves are capped
        (AnalysisScore(mate=-2), -1900),
        (AnalysisScore(mate=0), -2100),  # side to move is checkmated
        (AnalysisScore(), None),
    ],
)
def test_score_to_cp(score, cp):
    assert score_to_cp(score) == cp


def test_classify_thresholds_and_noise_floor():
    assert classify(100, 0.35) == "blunder"
    assert classify(100, 0.3) == "blunder"
    assert classify(100, 0.25) == "mistake"
    assert classify(100, 0.15) == "inaccuracy"
    assert classify(100, 0.05) is None
    assert classify(29, 0.5) is None  # below MIN_CP_LOSS


def test_playing_the_best_move_loses_nothing():
    scored = score_move(AnalysisScore(cp=40), None)
    assert scored == {
        "evaluation": {"cp": 40, "mate": None},
        "loss_cp": 0,
        "win_chance_loss": 0.0,
        "classification": None,
    }


def test_losing_move_in_equal_position_is_a_blunder():
    # After the move the opponent is +300, i.e. the player is -300
    scored = score_move(AnalysisScore(cp=0), AnalysisScore(cp=300))
    assert scored["evaluation"] == {"cp": -300, "mate": None}
    assert scored["loss_cp"] == 300
    assert scored["classification"] == "blunder"


def test_same_cp_loss_matters_less_when_already_winning():
    # 200 cp dropped from +900 barely changes the winning chances
    assert (
        score_move(AnalysisScore(cp=900), AnalysisScore(cp=-700))["classification"]
        is None
    )
    # 150 cp dropped from +600 is an inaccuracy
    assert (
        score_move(AnalysisScore(cp=600), AnalysisScore(cp=-450))["classification"]
        == "inaccuracy"
    )


def test_engine_noise_never_reports_a_gain():
    scored = score_move(AnalysisScore(cp=20), AnalysisScore(cp=-60))
    assert scored["loss_cp"] == 0
    assert scored["win_chance_loss"] == 0.0


def test_missing_mate_for_the_player():
    # Mate in 2 was available, the move only keeps +5: a 0.225 drop in winning chances.
    # Lichess flags lost mates separately; here they follow the same thresholds.
    scored = score_move(AnalysisScore(mate=2), AnalysisScore(cp=-500))
    assert scored["classification"] == "mistake"


def test_delivering_checkmate():
    scored = score_move(AnalysisScore(mate=1), AnalysisScore(mate=0))
    assert scored["evaluation"] == {"cp": None, "mate": 0}
    assert scored["loss_cp"] == 0


def test_unscored_when_engine_has_no_score():
    assert score_move(AnalysisScore(), AnalysisScore(cp=10)) == {}
    assert score_move(AnalysisScore(cp=10), AnalysisScore()) == {}


# -- Report builder ------------------------------------------------------------


def test_builder_merges_games_per_colour():
    builder = ReviewReportBuilder("me", max_plies=4)
    assert builder.add_game(make_game("1. e4 e5 2. Nf3 Nc6 3. Bb5", result="1-0"))
    assert builder.add_game(make_game("1. e4 e5 2. Nf3 Nf6", result="1/2-1/2"))
    assert builder.add_game(
        make_game("1. d4 d5", white="them", black="me", result="0-1")
    )

    white = builder.repertoires["white"]
    black = builder.repertoires["black"]
    assert white["games"] == 2 and black["games"] == 1

    start = white["positions"][normalize_fen(chess.Board())]
    assert start["occurrences"] == 2
    assert start["wins"] == 1 and start["draws"] == 1
    assert start["player_to_move"] is True
    assert start["played_moves"] == {"e2e4": {"count": 2}}

    after_nf3 = white["positions"][fen_after("e2e4", "e7e5", "g1f3")]
    assert after_nf3["player_to_move"] is False
    assert after_nf3["line"] == ["e2e4", "e7e5", "g1f3"]
    assert after_nf3["played_moves"] == {"b8c6": {"count": 1}, "g8f6": {"count": 1}}

    # max_plies=4: the position before 3. Bb5 is never recorded
    assert fen_after("e2e4", "e7e5", "g1f3", "b8c6") not in white["positions"]

    # The start position in the black repertoire is the opponent's move
    assert black["positions"][normalize_fen(chess.Board())]["player_to_move"] is False


def test_builder_merges_transpositions():
    builder = ReviewReportBuilder("me", max_plies=4)
    builder.add_game(make_game("1. Nf3 d5 2. d4 Nf6"))
    builder.add_game(make_game("1. d4 d5 2. Nf3 e6"))
    position = builder.repertoires["white"]["positions"][
        fen_after("d2d4", "d7d5", "g1f3")
    ]
    assert position["occurrences"] == 2
    assert position["line"] == [
        "g1f3",
        "d7d5",
        "d2d4",
    ]  # from the first game that reached it


def test_builder_skips_other_players_and_custom_setups():
    builder = ReviewReportBuilder("me", max_plies=4)
    assert not builder.add_game(make_game("1. e4 e5", white="a", black="b"))
    assert not builder.add_game(
        make_game("1. Ke2", fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    )
    assert not builder.add_game(
        make_game("1. e4 e5", white="Me")
    )  # names match exactly
    assert builder.games_skipped == 3 and builder.games_included == 0


# -- Service: end to end with a fake analyzer ----------------------------------


class FakeService(AnalyzerService):
    """AnalyzerService with the cached analyzer chain replaced by fixed evaluations, on an in-memory database."""

    def __init__(self, evaluations: dict[str, tuple[int, str | None]], max_plies: int):
        self.fake_db = FakeDB()
        super().__init__(db=self.fake_db)  # type: ignore[arg-type]
        self.max_plies = max_plies
        self.evaluations = evaluations
        self.analyzed: list[str] = []

    async def analyze(self, board: chess.Board) -> AnalysisResult | None:
        fen = normalize_fen(board)
        self.analyzed.append(fen)
        if fen not in self.evaluations:
            return None
        cp, best = self.evaluations[fen]
        return AnalysisResult(
            source="local_stockfish",
            depth=12,
            score=AnalysisScore(cp=cp),
            best_move_uci=best,
        )

    def review_and_load(self, games, player: str = "me", color: str = "white"):
        """Run a review, then load the saved positions of one repertoire."""
        report = asyncio.run(
            self.review(games, player, tree_id="job-1", expires_at=None)
        )
        fens = [
            d["fen"]
            for d in self.fake_db["review_positions"].documents
            if d["color"] == color
        ]
        positions = asyncio.run(get_positions(self.db, "job-1", color, fens))
        return report, positions


def test_review_detects_and_ranks_recurring_mistakes():
    start = normalize_fen(chess.Board())
    before_move_2 = fen_after("e2e4", "e7e5")
    service = FakeService(
        {
            start: (30, "e2e4"),
            before_move_2: (40, "g1f3"),
            fen_after("e2e4", "e7e5", "d1h5"): (150, None),  # black is +150 after Qh5
            fen_after("e2e4", "e7e5", "f2f3"): (
                60,
                None,
            ),  # black is +60 after f3: an inaccuracy
        },
        max_plies=3,
    )
    games = [
        make_game("1. e4 e5 2. Nf3"),
        make_game("1. e4 e5 2. Qh5"),
        make_game("1. e4 e5 2. Qh5"),
        make_game("1. e4 e5 2. f3"),
    ]

    report, positions = service.review_and_load(games)
    white = report["repertoires"]["white"]

    # Only the player's positions and the positions after non-best moves are analyzed
    assert sorted(service.analyzed) == sorted(
        [
            start,
            before_move_2,
            fen_after("e2e4", "e7e5", "d1h5"),
            fen_after("e2e4", "e7e5", "f2f3"),
        ]
    )

    position = positions[before_move_2]
    assert "line" not in position  # only mistakes carry their line
    assert position["best_move"] == "g1f3"
    assert position["evaluation"] == {
        "cp": 40,
        "mate": None,
        "depth": 12,
        "source": "local_stockfish",
    }
    assert position["played_moves"]["g1f3"]["loss_cp"] == 0
    assert position["played_moves"]["d1h5"]["loss_cp"] == 190
    assert position["played_moves"]["d1h5"]["classification"] == "blunder"
    assert position["played_moves"]["f2f3"]["classification"] == "inaccuracy"

    assert [
        (m["move"], m["count"], m["classification"]) for m in white["mistakes"]
    ] == [
        ("d1h5", 2, "blunder"),
        ("f2f3", 1, "inaccuracy"),
    ]
    top = white["mistakes"][0]
    assert top["line"] == ["e2e4", "e7e5"]
    assert top["best_move"] == "g1f3"
    assert top["evaluation_after"] == {"cp": -150, "mate": None}
    assert top["impact"] == pytest.approx(2 * top["win_chance_loss"])
    assert white["counts"] == {"inaccuracy": 1, "mistake": 0, "blunder": 1}
    assert white["mistakes_total"] == 2
    assert (
        "positions" not in white
    )  # the tree is stored per position, not on the report
    assert report["summary"] == {
        "player": "me",
        "games_included": 4,
        "games_skipped": 0,
        "max_plies": 3,
    }


def test_review_survives_failed_analysis():
    # Nothing can be evaluated: the report still completes, unscored
    service = FakeService({}, max_plies=4)
    report, positions = service.review_and_load([make_game("1. e4 e5 2. Nf3")])
    start = positions[normalize_fen(chess.Board())]
    assert start["evaluation"] is None
    assert start["played_moves"] == {"e2e4": {"count": 1}}
    assert report["repertoires"]["white"]["mistakes"] == []


def test_checkmate_is_scored_without_the_engine():
    service = FakeService({}, max_plies=8)
    board = chess.Board()
    for uci in ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6"]:
        board.push_uci(uci)
    score = asyncio.run(service._evaluate_after(board, chess.Move.from_uci("h5f7")))
    assert score == AnalysisScore(mate=0)
    assert service.analyzed == []
