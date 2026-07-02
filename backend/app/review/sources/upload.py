import structlog

from app.review.sources.base import ReviewSource
from app.review.schemas import UploadSourceConfig
from typing import Generator, Any
from chess.pgn import read_game, Game
from pathlib import Path


log = structlog.get_logger()


class UploadSource(ReviewSource):
    def __init__(self, source_config: UploadSourceConfig):
        self._source_config = source_config

    @property
    def player(self) -> str:
        return self._source_config.player

    def iter_games(self) -> Generator[Game | None, Any, Any]:
        game_path = Path(self._source_config.temp_file)
        log.info("review_upload_source_opened", temp_file=str(game_path))
        with open(game_path) as source_file:
            games_seen = 0
            while (game := read_game(source_file)) is not None:
                games_seen += 1
                yield game
        game_path.unlink()
        log.info("review_upload_source_completed", temp_file=str(game_path), games_seen=games_seen)
