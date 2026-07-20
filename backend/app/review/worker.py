import structlog

from app.review.queue import ReviewQueue
from app.review.service import AnalyzerService
from app.review.sources.factory import create_source


log = structlog.get_logger()


async def worker(review_queue: ReviewQueue, service: AnalyzerService):
    log.info("review_worker_started")
    while True:
        job = await review_queue.dequeue()
        try:
            log.info("review_job_started", job_id=str(job.job_id))
            review_queue.set_status(job.job_id, "running")
            source = create_source(job)
            games_seen = 0
            reports = []
            for game in source.iter_games():
                games_seen += 1
                report = await service.analyze_game(game, source.player)
                reports.append(report)
            review_queue.set_status(job.job_id, "completed", reports=reports)
            log.info("review_job_completed", job_id=str(job.job_id), games_seen=games_seen)
        except Exception as e:
            review_queue.set_status(job.job_id, "failed", str(e))
            log.error("review_job_failed", job_id=str(job.job_id), error=str(e), exc_info=True)
        finally:
            review_queue._queue.task_done()
