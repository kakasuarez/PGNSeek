"""
app/review/service.py

Opening review service.
"""

from __future__ import annotations

from app.review.schemas import ReviewJob
from app.review.sources.base import ReviewSource
from app.review.sources.factory import create_source


def process_review(job: ReviewJob):
    source: ReviewSource = create_source(job)
    for game in source.iter_games():
        if not game:
            break
        # TODO: Review `game` here.
