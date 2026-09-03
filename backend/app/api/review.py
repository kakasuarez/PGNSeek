"""
app/api/review.py

Opening review endpoint.
    POST /api/v1/review  —  submit a PGN file for opening analysis
"""

import structlog
from typing import cast
from uuid import UUID

from fastapi import UploadFile, Form, APIRouter, Depends, HTTPException
from supabase import create_client, Client

from app.review.schemas import (
    UploadSourceConfig,
    ReviewJob,
)
from app.review.tasks import review_opening_task as review_opening
from app.db import get_db
from app.config import settings
from motor.motor_asyncio import AsyncIOMotorDatabase
from celery import Task

log = structlog.get_logger()
router = APIRouter()

# Initialize Supabase client
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


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
    job = await db.review_jobs.find_one({"_id": str(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Review job not found")
    if job.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Review job is not completed yet")
    
    reports = job.get("reports")
    if reports is None:
        raise HTTPException(status_code=404, detail="Reports not found for this job")
        
    return {"job_id": job_id, "reports": reports}


@router.post(
    "/review",
    summary="Run opening review on a PGN file",
    description=(
        "Analyze the first N plies of every game in the PGN, "
        "deduplicate positions, evaluate with Stockfish, "
        "and return a position report + mistake report."
    ),
)
async def review(
    pgn_file: UploadFile, 
    player: str = Form(),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    log.info("review_request", pgn_file=pgn_file, player=player)
    
    try:
        job = ReviewJob(
            source="upload",
            source_config=UploadSourceConfig(
                temp_file="", player=player # temp_file will be replaced by supabase key
            ),
        )
        
        object_key = f"{job.job_id}.pgn"
        
        # Read the file contents
        file_contents = await pgn_file.read()
        
        # Upload to Supabase Storage
        supabase.storage.from_(settings.SUPABASE_BUCKET).upload(
            path=object_key,
            file=file_contents,
            file_options={"content-type": "application/x-chess-pgn"}
        )
        
        # Update job with the actual object key
        job.source_config.temp_file = object_key
        
        await db.review_jobs.insert_one({"_id": str(job.job_id), "status": "queued"})
        review_opening_task = cast(Task, review_opening)
        review_opening_task.delay(job.model_dump(mode="json"))
        
        return {"status": "queued", "job_id": job.job_id}
    except Exception as e:
        log.error("error_review_request", e=str(e), exc_info=True)
    return {"status": "error"}
