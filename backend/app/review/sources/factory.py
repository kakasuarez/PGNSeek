import structlog

from app.review.sources.base import ReviewSource
from app.review.sources.upload import UploadSource
from app.review.schemas import ReviewJob


log = structlog.get_logger()


def create_source(job: ReviewJob) -> ReviewSource:
    log.info("review_source_created", job_id=str(job.job_id), source=job.source)
    return UploadSource(job.source_config)
