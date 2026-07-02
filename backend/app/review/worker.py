from app.review.queue import ReviewQueue
from app.review.service import AnalyzerService
from app.review.sources.base import ReviewSource
from app.review.sources.factory import create_source


async def worker(review_queue: ReviewQueue):
    service = AnalyzerService()
    while True:
        job = await review_queue.dequeue()
        source = create_source(job)
        try:
            for game in source.iter_games():
                await service.analyze_game(game, source.player)
        finally:
            review_queue._queue.task_done()
