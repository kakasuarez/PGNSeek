"""
app/api/review.py

Opening review endpoints.
    POST /api/v1/review                              —  submit a PGN file for opening analysis
    GET  /api/v1/review/{job_id}                     —  job status
    GET  /api/v1/review/{job_id}/reports             —  summary and ranked mistakes
    GET  /api/v1/review/{job_id}/positions           —  one position plus its most played children
    POST /api/v1/review/{job_id}/positions/batch     —  several positions, e.g. along a line
"""

import structlog
from datetime import datetime, timedelta, timezone
from typing import Literal, cast
from uuid import UUID

import chess
from fastapi import UploadFile, Form, APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase import create_client, Client

from app.review.schemas import (
    UploadSourceConfig,
    ReviewJob,
)
from app.review.tasks import review_opening_task as review_opening
from app.review.report import normalize_fen
from app.review.store import get_position_with_children, get_positions
from app.db import get_db
from app.config import settings
from motor.motor_asyncio import AsyncIOMotorDatabase
from celery import Task

log = structlog.get_logger()
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# Initialize Supabase client
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


# A mistake's line is at most OPENING_REVIEW_MAX_PLIES long, so batches stay small
MAX_BATCH_FENS = 64

Color = Literal["white", "black"]


class PositionsBatchRequest(BaseModel):
    color: Color
    fens: list[str] = Field(max_length=MAX_BATCH_FENS)


def _normalize_fen(fen: str) -> str:
    try:
        return normalize_fen(chess.Board(fen))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid FEN: {fen}")


async def _completed_job(db: AsyncIOMotorDatabase, job_id: UUID, projection: dict | None = None) -> dict:
    job = await db.review_jobs.find_one({"_id": str(job_id)}, projection)
    if not job:
        raise HTTPException(status_code=404, detail="Review job not found")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Review job is not completed yet")
    return job


# @router.get("/review/debug/counts")
# async def review_analysis_counts(request: Request):
#     service = request.app.state.analysis_service
#     return service.analysis_counts


@router.get("/review/{job_id}")
async def review_status(job_id: UUID, db: AsyncIOMotorDatabase = Depends(get_db)):
    job = await db.review_jobs.find_one({"_id": str(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Review job not found")
    
    status_response = {"status": job.get("status")}
    if "error" in job:
        status_response["error"] = job["error"]
        
    return {"job_id": job_id, **status_response}


@router.get("/review/{job_id}/reports")
async def review_reports(job_id: UUID, db: AsyncIOMotorDatabase = Depends(get_db)):
    job = await _completed_job(db, job_id)
    report = job.get("report")
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found for this job")

    return {"job_id": job_id, "report": report}


@router.get(
    "/review/{job_id}/positions",
    summary="Get a position from a review's tree",
    description=(
        "Returns the position (null if no game reached it) and the positions after its "
        "most played moves, so the client can prefetch them."
    ),
)
async def review_position(
    job_id: UUID,
    color: Color = Query(description="Repertoire: the colour the player had"),
    fen: str = Query(description="Position FEN; move clocks are optional"),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    await _completed_job(db, job_id, {"status": 1})
    position, children = await get_position_with_children(db, str(job_id), color, _normalize_fen(fen))
    return {"position": position, "children": children}


@router.post(
    "/review/{job_id}/positions/batch",
    summary="Get several positions from a review's tree",
    description="Returns the positions found, keyed by normalized FEN. FENs no game reached are left out.",
)
async def review_positions_batch(
    job_id: UUID, body: PositionsBatchRequest, db: AsyncIOMotorDatabase = Depends(get_db)
):
    await _completed_job(db, job_id, {"status": 1})
    fens = [_normalize_fen(fen) for fen in body.fens]
    return {"positions": await get_positions(db, str(job_id), body.color, fens)}


@router.post(
    "/review",
    summary="Run opening review on a PGN file",
    description=(
        "Analyze the first N plies of every game in the PGN, "
        "deduplicate positions, evaluate them with the Lichess cloud eval or Stockfish, "
        "and build a position tree plus a ranked report of the player's mistakes. "
        "Fetch the result from GET /review/{job_id}/reports once the job is completed."
    ),
)
@limiter.limit(f"{settings.REVIEW_RATE_LIMIT_PER_MINUTE}/minute")
async def review(
    request: Request,
    pgn_file: UploadFile,
    player: str = Form(),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    log.info("review_request", pgn_file=pgn_file, player=player)

    # Read one byte past the limit so oversized files are detected without loading them fully
    file_contents = await pgn_file.read(settings.REVIEW_MAX_UPLOAD_BYTES + 1)
    if len(file_contents) > settings.REVIEW_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"PGN file exceeds {settings.REVIEW_MAX_UPLOAD_BYTES // 1_000_000} MB limit",
        )

    try:
        job = ReviewJob(
            source="upload",
            source_config=UploadSourceConfig(
                temp_file="", player=player # temp_file will be replaced by supabase key
            ),
        )
        
        object_key = f"{job.job_id}.pgn"

        # Upload to Supabase Storage
        supabase.storage.from_(settings.SUPABASE_BUCKET).upload(
            path=object_key,
            file=file_contents,
            file_options={"content-type": "application/x-chess-pgn"}
        )
        
        # Update job with the actual object key
        job.source_config.temp_file = object_key
        
        # Jobs that never complete still expire; the worker resets this on completion
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.REVIEW_TTL_SECONDS)
        await db.review_jobs.insert_one({"_id": str(job.job_id), "status": "queued", "expires_at": expires_at})
        review_opening_task = cast(Task, review_opening)
        review_opening_task.delay(job.model_dump(mode="json"))
        
        return {"status": "queued", "job_id": job.job_id}
    except Exception as e:
        log.error("error_review_request", e=str(e), exc_info=True)
    raise HTTPException(status_code=500, detail="Could not submit the review job. Please try again.")
