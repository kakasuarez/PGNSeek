from app.review.sources.base import ReviewSource
from app.review.sources.upload import UploadSource
from app.review.schemas import ReviewJob


def create_source(job: ReviewJob) -> ReviewSource:
    # if isinstance(job.source_config, UploadSourceConfig):
    # ...

    # elif isinstance(job.source_config, LichessSourceConfig):
    # ...
    return UploadSource(job.source_config)
