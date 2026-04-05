"""
app/config.py

Single source of truth for all runtime configuration.
All values come from environment variables (or .env file).
Never import a raw env var anywhere else in the codebase — always use `settings`.
"""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Elasticsearch
    ES_HOST: str = "http://localhost:9200"
    ES_INDEX: str = "chess_games"
    ES_INDEX_ALIAS: str = "chess_games"
    ES_BULK_BATCH_SIZE: int = 500
    ES_MAX_RESULT_WINDOW: int = 10000

    # Ingestion
    PGN_DATA_DIR: str = "./data/pgn"
    INGESTION_STATE_FILE: str = "./data/ingestion_state.json"
    MIN_YEAR: int = 2010

    # Feature extraction thresholds
    AGGRESSION_THRESHOLD: float = 3.0
    SACRIFICE_DELTA: int = 3
    ENDGAME_MAX_PIECES: int = 12

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100
    RATE_LIMIT_PER_MINUTE: int = 60

    # Caching
    CACHE_TTL_SECONDS: int = 300
    CACHE_MAX_SIZE: int = 1000

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    ENV: str = "development"

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()

    @field_validator("ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in {"development", "production"}:
            raise ValueError("ENV must be 'development' or 'production'")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached settings singleton. Call get_settings() everywhere —
    the lru_cache ensures the .env file is only read once.
    """
    return Settings()


# Convenience shortcut — `from app.config import settings`
settings = get_settings()
