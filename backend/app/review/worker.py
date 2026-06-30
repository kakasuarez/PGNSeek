from app.review.queue import ReviewQueue
from app.review.service import process_review


async def worker(review_queue: ReviewQueue):
    while True:
        job = await review_queue.dequeue()
        try:
            process_review(job)
        finally:
            review_queue._queue.task_done()
