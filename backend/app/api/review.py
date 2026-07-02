"""
app/api/review.py

Opening review endpoint.
    POST /api/v1/review  —  submit a PGN file for opening analysis
"""

import structlog
import tempfile
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile, Form, APIRouter, Request, HTTPException

from app.review.schemas import (
    UploadSourceConfig,
    ReviewJob,
)

log = structlog.get_logger()
router = APIRouter()


# @router.get("/review/debug/counts")
# async def review_analysis_counts(request: Request):
#     service = request.app.state.analysis_service
#     return service.analysis_counts


@router.get("/review/{job_id}")
async def review_status(request: Request, job_id: UUID):
    status = request.app.state.review_queue.get_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Review job not found")
    return {"job_id": job_id, **status}


@router.post(
    "/review",
    summary="Run opening review on a PGN file",
    description=(
        "Analyze the first N plies of every game in the PGN, "
        "deduplicate positions, evaluate with Stockfish, "
        "and return a position report + mistake report."
    ),
)
async def review(request: Request, pgn_file: UploadFile, player: str = Form()):
    log.info("review_request", pgn_file=pgn_file, player=player)
    # Currently using filesystem directly, may later add a storage layer.
    temp_file = tempfile.NamedTemporaryFile(suffix=".pgn", delete=False)
    review_queue = request.app.state.review_queue
    try:
        shutil.copyfileobj(pgn_file.file, temp_file)
        job = ReviewJob(
            source="upload",
            source_config=UploadSourceConfig(
                temp_file=str(Path(temp_file.name)), player=player
            ),
        )
        await review_queue.enqueue(job)
        return {"status": "queued", "job_id": job.job_id}
    except Exception as e:
        log.error("error_review_request", e)
    finally:
        temp_file.close()
    return {"status": "error"}
