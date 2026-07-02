from app.review.sources.base import ReviewSource
from app.review.schemas import UploadSourceConfig
from typing import Generator, Any
from chess.pgn import read_game, Game
from pathlib import Path


class UploadSource(ReviewSource):
    def __init__(self, source_config: UploadSourceConfig):
        self._source_config = source_config

    @property
    def player(self) -> str:
        return self._source_config.player

    def iter_games(self) -> Generator[Game | None, Any, Any]:
        game_path = Path(self._source_config.temp_file)
        with open(game_path) as source_file:
            while (game := read_game(source_file)) is not None:
                yield game
        game_path.unlink()
