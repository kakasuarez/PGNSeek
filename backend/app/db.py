from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from app.config import settings

async def startup_db(app):
    """Initialize MongoDB client on app startup."""
    app.state.mongo = AsyncIOMotorClient(settings.MONGODB_URI)

async def shutdown_db(app):
    """Close MongoDB client on app shutdown."""
    app.state.mongo.close()

async def get_db(request: Request) -> AsyncIOMotorDatabase:
    """Get the MongoDB database."""
    return request.app.state.mongo[settings.MONGODB_DB]

def games_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:
    return db["chess_games"]

def position_evals_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:
    return db["position_evals"]

def lichess_cache_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:
    return db["lichess_cache"]

def review_jobs_collection(db: AsyncIOMotorDatabase) -> AsyncIOMotorCollection:
    return db["review_jobs"]
