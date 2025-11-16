#!/usr/bin/env python3
"""
FastAPI Server for Chess Game Retrieval Engine

Provides a REST API endpoint for semantic search of chess games.
"""

from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from search import GameSearchEngine


# Pydantic models for request/response validation
class SearchRequest(BaseModel):
    """Request model for game search."""

    query: str = Field(..., min_length=1, description="Natural language search query")
    top_k: int = Field(
        10, ge=1, le=100, description="Number of results to return (1-100)"
    )


class GameResult(BaseModel):
    """Model for a single game result."""

    rank: int
    white: str
    black: str
    result: str
    eco: str
    opening: str
    event: str
    site: str
    date: str
    round: str
    white_elo: str
    black_elo: str
    pgn: str
    uci_moves: List[str]
    distance: float
    similarity_score: float


class SearchResponse(BaseModel):
    """Response model for game search."""

    query: str
    top_k: int
    total_results: int
    results: List[GameResult]


# Initialize FastAPI app
app = FastAPI(
    title="Chess Game Retrieval Engine",
    description="Semantic search for chess games using LLM embeddings and FAISS",
    version="1.0.0",
)

# Global search engine instance (loaded on startup)
search_engine: Optional[GameSearchEngine] = None


@app.on_event("startup")
async def startup_event():
    """Initialize the search engine on server startup."""
    global search_engine
    try:
        print("Initializing search engine...")
        search_engine = GameSearchEngine(index_dir="./index")
        print("Search engine ready!")
    except Exception as e:
        print(f"Error initializing search engine: {e}")
        print("Make sure to build the FAISS index first using embed_games.py")
        raise


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Chess Game Retrieval Engine",
        "version": "1.0.0",
        "endpoints": {
            "/search": "Search for chess games (GET or POST)",
            "/health": "Health check endpoint",
            "/docs": "Interactive API documentation",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    if search_engine is None:
        raise HTTPException(status_code=503, detail="Search engine not initialized")

    return {
        "status": "healthy",
        "index_size": search_engine.index.ntotal,
        "total_games": len(search_engine.metadata),
    }


@app.get("/search", response_model=SearchResponse)
async def search_get(
    query: str = Query(..., min_length=1, description="Natural language search query"),
    top_k: int = Query(
        10, ge=1, le=100, description="Number of results to return (1-100)"
    ),
):
    """
    Search for chess games using a natural language query (GET method).

    Example: /search?query=Magnus%20Carlsen%20wins&top_k=5
    """
    return await _perform_search(query, top_k)


@app.post("/search", response_model=SearchResponse)
async def search_post(request: SearchRequest):
    """
    Search for chess games using a natural language query (POST method).

    Example request body:
    {
        "query": "Sicilian Defense games with tactical sacrifices",
        "top_k": 10
    }
    """
    return await _perform_search(request.query, request.top_k)


async def _perform_search(query: str, top_k: int) -> SearchResponse:
    """
    Internal function to perform the search.

    Args:
        query: Search query string
        top_k: Number of results to return

    Returns:
        SearchResponse with results
    """
    if search_engine is None:
        raise HTTPException(status_code=503, detail="Search engine not initialized")

    try:
        # Perform search
        results = search_engine.search_games(query, top_k)

        # Convert to response model
        game_results = [
            GameResult(
                rank=game["rank"],
                white=game["white"],
                black=game["black"],
                result=game["result"],
                eco=game["eco"],
                opening=game["opening"],
                event=game["event"],
                site=game["site"],
                date=game["date"],
                round=game["round"],
                white_elo=game["white_elo"],
                black_elo=game["black_elo"],
                pgn=game["pgn"],
                uci_moves=game["uci_moves"],
                distance=game["distance"],
                similarity_score=game["similarity_score"],
            )
            for game in results
        ]

        return SearchResponse(
            query=query,
            top_k=top_k,
            total_results=len(game_results),
            results=game_results,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 handler."""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Endpoint not found",
            "message": "Visit /docs for API documentation",
        },
    )


def main():
    """Run the FastAPI server."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Chess Game Retrieval Engine API Server"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to bind to (default: 8000)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )

    args = parser.parse_args()

    print(f"Starting Chess Game Retrieval Engine API Server...")
    print(f"Server will be available at: http://{args.host}:{args.port}")
    print(f"API documentation at: http://{args.host}:{args.port}/docs")

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
