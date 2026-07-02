from app.review.queue import ReviewQueue
from app.review.service import AnalyzerService
from app.review.sources.factory import create_source


async def worker(review_queue: ReviewQueue, service: AnalyzerService):
    while True:
        job = await review_queue.dequeue()
        try:
            review_queue.set_status(job.job_id, "running")
            source = create_source(job)
            for game in source.iter_games():
                await service.analyze_game(game, source.player)
            review_queue.set_status(job.job_id, "completed")
        except Exception as e:
            review_queue.set_status(job.job_id, "failed", str(e))
        finally:
            review_queue._queue.task_done()
