from asyncio import Queue
from uuid import UUID

from app.review.schemas import ReviewJob


class ReviewQueue:
    def __init__(self):
        self._queue: Queue[ReviewJob] = Queue()
        self.statuses: dict[UUID, dict[str, str]] = {}

    async def enqueue(self, job: ReviewJob):
        self.statuses[job.job_id] = {"status": "queued"}
        await self._queue.put(job)

    async def dequeue(self) -> ReviewJob:
        return await self._queue.get()

    def set_status(self, job_id: UUID, status: str, error: str | None = None) -> None:
        payload = {"status": status}
        if error:
            payload["error"] = error
        self.statuses[job_id] = payload

    def get_status(self, job_id: UUID) -> dict[str, str] | None:
        return self.statuses.get(job_id)
