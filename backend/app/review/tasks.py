import asyncio
import os
import tempfile
import structlog
from celery import Celery
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.review.schemas import ReviewJob
from app.review.sources.factory import create_source
from app.review.service import AnalyzerService
from supabase import create_client, Client

log = structlog.get_logger()

# Initialize Supabase client
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

celery_app = Celery(
    "pgnseek_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)


async def process_job(job: ReviewJob):
    job_id = str(job.job_id)
    
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB]
    
    await db.review_jobs.update_one(
        {"_id": job_id},
        {"$set": {"status": "running"}},
        upsert=True
    )
    
    object_key = None
    local_temp_path = None
    
    try:
        object_key = job.source_config.temp_file
        local_temp_fd, local_temp_path = tempfile.mkstemp(suffix=".pgn")
        
        # Download the PGN from Supabase Storage
        res = await asyncio.to_thread(
            supabase.storage.from_(settings.SUPABASE_BUCKET).download, object_key
        )
        
        with os.fdopen(local_temp_fd, "wb") as f:
            f.write(res)
            
        job.source_config.temp_file = local_temp_path
        
        source = create_source(job)
        player = source.player
        
        service = AnalyzerService(db)
        
        reports = []
        for game in source.iter_games():
            if game is None:
                continue
                
            report = await service.analyze_game(game, player)
            if report:
                reports.append(report)
                
        await db.review_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "completed", "reports": reports}}
        )
        log.info("task_review_opening_completed", job_id=job_id)
        
    except Exception as exc:
        log.error("task_review_opening_failed", job_id=job_id, error=str(exc), exc_info=True)
        await db.review_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "failed", "error": str(exc)}}
        )
        raise exc
    finally:
        # Clean up local temp file and Supabase storage
        try:
            if local_temp_path is not None and os.path.exists(local_temp_path):
                os.remove(local_temp_path)
            if object_key is not None:
                await asyncio.to_thread(
                    supabase.storage.from_(settings.SUPABASE_BUCKET).remove, [object_key]
                )
        except Exception as cleanup_err:
            log.warning("cleanup_failed", error=str(cleanup_err))


@celery_app.task(bind=True, name="app.review.tasks.review_opening_task")
def review_opening_task(self, job_dict: dict):
    job = ReviewJob(**job_dict)
    log.info("task_review_opening_started", job_id=str(job.job_id))
    asyncio.run(process_job(job))
