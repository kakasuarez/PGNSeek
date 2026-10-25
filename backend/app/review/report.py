"""
app/review/report.py

Opening review report: one position tree per colour built from the player's
games, with each of the player's moves scored against the engine's best move.

Moves are classified by the drop in winning chances, using the Lichess formula
and thresholds. Losses below MIN_CP_LOSS are treated as engine noise.

Report shape (stored on the review job as `report`):
    {
    "summary": {"player", "games_included", "games_skipped", "max_plies"},
    "repertoires": {
        "white" | "black": {
        "games": int,
        "counts": {"inaccuracy": n, "mistake": n, "blunder": n},   # over all mistakes
        "mistakes": [Mistake, ...],   # top MAX_MISTAKES, ranked by impact, highest first
        "mistakes_total": int
        }
    }
    }

The position tree is not part of the report: it can outgrow MongoDB's 16 MB
document limit, so each position is stored separately (see app/review/store.py).

Position:
    fen, side_to_move, player_to_move, occurrences, wins, draws,
    line         — UCI moves from the start position of the first game that reached it
                   (kept in memory to build mistakes; not stored with the position)
    best_move    — engine best move (player-to-move positions only)
    evaluation   — {cp, mate, depth, source} (player-to-move positions only)
    played_moves — {uci: {count, evaluation, loss_cp, win_chance_loss, classification}}
                   (scoring fields only on player-to-move positions)

All evaluations are from the reviewed player's point of view. On a played
move, mate 0 means the move delivers checkmate.

Mistake:
    fen, line, move, count, best_move, evaluation_before, evaluation_after,
    loss_cp, win_chance_loss, classification,
    impact — count × win_chance_loss
"""

import math
from typing import Any, Iterator

import chess
from chess.pgn import Game

from app.review.schemas import AnalysisResult, AnalysisScore

# Lichess thresholds on the drop in winning chances (scale -1..1), worst first
CLASSIFICATION_THRESHOLDS = [(0.3, "blunder"), (0.2, "mistake"), (0.1, "inaccuracy")]
# Smaller losses are within engine noise at review depths
MIN_CP_LOSS = 30
# Mistakes stored on the report per colour; counts still cover all of them
MAX_MISTAKES = 200


# -- Scoring -------------------------------------------------------------------


def normalize_fen(board: chess.Board) -> str:
    return " ".join(board.fen().split(" ")[:4])


def score_to_cp(score: AnalysisScore) -> int | None:
    """Centipawn equivalent from the side to move's point of view (Lichess mate conversion)."""
    if score.mate is not None:
        # mate 0: the side to move is checkmated
        sign = 1 if score.mate > 0 else -1
        return sign * (21 - min(10, abs(score.mate))) * 100
    return score.cp


def winning_chances(cp: int) -> float:
    """Lichess winning chances in -1..1 for a centipawn score."""
    cp = max(-1000, min(1000, cp))
    return 2 / (1 + math.exp(-0.00368208 * cp)) - 1


def classify(loss_cp: int, win_chance_loss: float) -> str | None:
    if loss_cp < MIN_CP_LOSS:
        return None
    for threshold, label in CLASSIFICATION_THRESHOLDS:
        if win_chance_loss >= threshold:
            return label
    return None


def score_move(best: AnalysisScore, after_move: AnalysisScore | None) -> dict[str, Any]:
    """
    Score a played move.

    best       — evaluation of the position before the move (player to move)
    after_move — evaluation of the position after the move (opponent to move),
                 or None if the player played the engine's best move
    """
    best_cp = score_to_cp(best)
    if best_cp is None:
        return {}
    if after_move is None:
        evaluation = {"cp": best.cp, "mate": best.mate}
        move_cp = best_cp
    else:
        after_cp = score_to_cp(after_move)
        if after_cp is None:
            return {}
        evaluation = {
            "cp": -after_move.cp if after_move.cp is not None else None,
            "mate": -after_move.mate if after_move.mate is not None else None,
        }
        move_cp = -after_cp

    # Engine noise can make a move look better than the best move; never report a gain
    loss_cp = max(0, best_cp - move_cp)
    win_chance_loss = round(
        max(0.0, winning_chances(best_cp) - winning_chances(move_cp)), 3
    )
    return {
        "evaluation": evaluation,
        "loss_cp": loss_cp,
        "win_chance_loss": win_chance_loss,
        "classification": classify(loss_cp, win_chance_loss),
    }


# -- Report builder ------------------------------------------------------------


class ReviewReportBuilder:
    """Collects positions from the player's games, then assembles the report."""

    def __init__(self, player: str, max_plies: int):
        self.player = player
        self.max_plies = max_plies
        self.games_included = 0
        self.games_skipped = 0
        self.repertoires: dict[str, dict[str, Any]] = {
            "white": {"games": 0, "positions": {}},
            "black": {"games": 0, "positions": {}},
        }

    def _player_color(self, game: Game) -> chess.Color | None:
        if game.headers.get("White") == self.player:
            return chess.WHITE
        if game.headers.get("Black") == self.player:
            return chess.BLACK
        return None

    def add_game(self, game: Game) -> bool:
        """Add a game to the tree. Returns False if the game was skipped."""
        player_color = self._player_color(game)
        # Lines are replayed from the standard start position, so custom setups are skipped
        if player_color is None or "FEN" in game.headers:
            self.games_skipped += 1
            return False

        self.games_included += 1
        repertoire = self.repertoires[
            "white" if player_color == chess.WHITE else "black"
        ]
        repertoire["games"] += 1
        result = game.headers.get("Result", "*")
        won = result == ("1-0" if player_color == chess.WHITE else "0-1")

        board = game.board()
        line: list[str] = []
        for move in game.mainline_moves():
            if len(line) >= self.max_plies:
                break
            fen = normalize_fen(board)
            position = repertoire["positions"].get(fen)
            if position is None:
                position = {
                    "fen": fen,
                    "side_to_move": "white" if board.turn == chess.WHITE else "black",
                    "player_to_move": board.turn == player_color,
                    "occurrences": 0,
                    "wins": 0,
                    "draws": 0,
                    "line": list(line),
                    "best_move": None,
                    "evaluation": None,
                    "played_moves": {},
                }
                repertoire["positions"][fen] = position
            position["occurrences"] += 1
            if won:
                position["wins"] += 1
            if result == "1/2-1/2":
                position["draws"] += 1
            played = position["played_moves"].setdefault(move.uci(), {"count": 0})
            played["count"] += 1

            board.push(move)
            line.append(move.uci())
        return True

    def positions(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """All positions, as (colour, position) pairs."""
        for color, repertoire in self.repertoires.items():
            for position in repertoire["positions"].values():
                yield color, position

    def player_positions(self) -> Iterator[dict[str, Any]]:
        """Positions where the player is to move, i.e. the ones to evaluate."""
        for repertoire in self.repertoires.values():
            for position in repertoire["positions"].values():
                if position["player_to_move"]:
                    yield position

    @staticmethod
    def set_evaluation(position: dict[str, Any], analysis: AnalysisResult) -> None:
        position["best_move"] = analysis.best_move_uci
        position["evaluation"] = {
            "cp": analysis.score.cp,
            "mate": analysis.score.mate,
            "depth": analysis.depth,
            "source": analysis.source,
        }

    def finish(self) -> dict[str, Any]:
        repertoires = {}
        for color, repertoire in self.repertoires.items():
            mistakes = []
            for position in repertoire["positions"].values():
                for uci, played in position["played_moves"].items():
                    if not played.get("classification"):
                        continue
                    mistakes.append(
                        {
                            "fen": position["fen"],
                            "line": position["line"],
                            "move": uci,
                            "count": played["count"],
                            "best_move": position["best_move"],
                            "evaluation_before": position["evaluation"],
                            "evaluation_after": played["evaluation"],
                            "loss_cp": played["loss_cp"],
                            "win_chance_loss": played["win_chance_loss"],
                            "classification": played["classification"],
                            "impact": round(
                                played["count"] * played["win_chance_loss"], 3
                            ),
                        }
                    )
            mistakes.sort(
                key=lambda m: (-m["impact"], -m["count"], m["fen"], m["move"])
            )
            counts = {label: 0 for _, label in reversed(CLASSIFICATION_THRESHOLDS)}
            for mistake in mistakes:
                counts[mistake["classification"]] += 1
            repertoires[color] = {
                "games": repertoire["games"],
                "counts": counts,
                "mistakes": mistakes[:MAX_MISTAKES],
                "mistakes_total": len(mistakes),
            }
        return {
            "summary": {
                "player": self.player,
                "games_included": self.games_included,
                "games_skipped": self.games_skipped,
                "max_plies": self.max_plies,
            },
            "repertoires": repertoires,
        }
