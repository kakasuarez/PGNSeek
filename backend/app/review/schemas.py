"""
app/review/schemas.py

Pydantic models exchanged between the API, queue and the worker.
"""

from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from typing import Literal

# ── Source Configs ──────────────────────────────────────────────────────────────


class UploadSourceConfig(BaseModel):
    temp_file: str
    player: str


# ── Reviews ──────────────────────────────────────────────────────────────


class ReviewJob(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    source: Literal["upload"]  # later separated in SourceConfigs
    source_config: (
        UploadSourceConfig  # later union with other SourceConfig e.g. Lichess
    )


# ── Analyis ──────────────────────────────────────────────────────────────


class AnalysisScore(BaseModel):
    cp: int | None = None
    mate: int | None = None


class AnalysisResult(BaseModel):
    source: Literal["local_stockfish"]
    depth: int
    score: AnalysisScore
    score_value: int | None = None
    best_move_uci: str | None = None
