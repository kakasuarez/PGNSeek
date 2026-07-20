from asyncio import Queue
from uuid import UUID
import structlog

from app.review.schemas import ReviewJob


log = structlog.get_logger()


class ReviewQueue:
    def __init__(self):
        self._queue: Queue[ReviewJob] = Queue()
        self.statuses: dict[UUID, dict[str, str]] = {}
        self.reports: dict[UUID, list] = {}

    async def enqueue(self, job: ReviewJob):
        self.statuses[job.job_id] = {"status": "queued"}
        await self._queue.put(job)
        log.info("review_job_queued", job_id=str(job.job_id), queue_size=self._queue.qsize())

    async def dequeue(self) -> ReviewJob:
        job = await self._queue.get()
        log.info("review_job_dequeued", job_id=str(job.job_id), queue_size=self._queue.qsize())
        return job

    def set_status(self, job_id: UUID, status: str, error: str | None = None, reports: list | None = None) -> None:
        payload = {"status": status}
        if error:
            payload["error"] = error
        if reports is not None:
            self.reports[job_id] = reports
        self.statuses[job_id] = payload
        log.info("review_job_status_updated", job_id=str(job_id), status=status, error=error)

    def get_status(self, job_id: UUID) -> dict[str, str] | None:
        return self.statuses.get(job_id)

    def get_reports(self, job_id: UUID) -> list | None:
        return self.reports.get(job_id)
