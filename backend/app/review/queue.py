from asyncio import Queue

from app.review.schemas import ReviewJob


class ReviewQueue:
    def __init__(self):
        self._queue: Queue[ReviewJob] = Queue()

    async def enqueue(self, job: ReviewJob):
        await self._queue.put(job)

    async def dequeue(self) -> ReviewJob:
        return await self._queue.get()
