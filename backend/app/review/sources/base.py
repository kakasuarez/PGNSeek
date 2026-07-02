from abc import ABC, abstractmethod
from typing import Generator, Any
from chess.pgn import Game


class ReviewSource(ABC):

    @property
    @abstractmethod
    def player(self) -> str:
        """
        Return the player name for which to review the games.
        """
        pass

    @abstractmethod
    def iter_games(self) -> Generator[Game | None, Any, Any]:
        """
        Yield PGN games one at a time.
        """
        pass
