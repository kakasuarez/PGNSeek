import asyncio
from typing import Any
from collections import Counter
import chess
import chess.pgn
import structlog
from celery import Celery
from pymongo import MongoClient

from app.config import settings
from app.review.analyzers.chain import AnalysisChain
from app.review.analyzers.cloud import CloudAnalyzer
from app.review.analyzers.local import LocalAnalyzer
from app.review.schemas import AnalysisResult, ReviewJob
from app.review.sources.factory import create_source
from supabase import create_client, Client

log = structlog.get_logger()

# Initialize Supabase client
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

celery_app = Celery(
    "pgnseek_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Use synchronous PyMongo in Celery tasks
client = MongoClient(settings.MONGODB_URI)
db = client[settings.MONGODB_DB]


def _normalize_fen(board: chess.Board) -> str:
    ep_square = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
    return " ".join([
        board.board_fen(),
        "w" if board.turn == chess.WHITE else "b",
        board.castling_xfen(),
        ep_square,
    ])


@celery_app.task(bind=True, name="app.tasks.review_opening_task")
def review_opening_task(self, job_dict: dict):
    job_id = str(job_dict.get("job_id"))
    log.info("task_review_opening_started", job_id=job_id)
    
    db.review_jobs.update_one(
        {"_id": job_id},
        {"$set": {"status": "running"}},
        upsert=True
    )
    
    try:
        job = ReviewJob(**job_dict)
        
        # Download the PGN from Supabase Storage to a temporary file
        object_key = job.source_config.temp_file
        
        # We need a local file for the PGN iterator
        import tempfile
        import os
        
        local_temp_fd, local_temp_path = tempfile.mkstemp(suffix=".pgn")
        
        res = supabase.storage.from_(settings.SUPABASE_BUCKET).download(object_key)
        with os.fdopen(local_temp_fd, "wb") as f:
            f.write(res)
        
        # Point the source config to the downloaded local file
        job.source_config.temp_file = local_temp_path
        
        source = create_source(job)
        player = source.player
        
        analyzer_chain = AnalysisChain([
            CloudAnalyzer(),
            LocalAnalyzer(depth=settings.OPENING_REVIEW_ENGINE_DEPTH)
        ])
        
        reports = []
        
        for game in source.iter_games():
            if game is None:
                continue
            
            white = game.headers.get("White", "")
            black = game.headers.get("Black", "")
            
            player_color = None
            if white == player:
                player_color = chess.WHITE
            elif black == player:
                player_color = chess.BLACK
                
            if player_color is None:
                continue
                
            buckets = {}
            board = game.board()
            node = game
            ply = 0
            max_plies = settings.OPENING_REVIEW_MAX_PLIES
            
            while node.variations and ply < max_plies:
                next_node = node.variation(0)
                move = next_node.move
                
                if board.turn == player_color:
                    fen = _normalize_fen(board)
                    if fen not in buckets:
                        buckets[fen] = {
                            "fen": fen,
                            "side_to_move": "white" if board.turn == chess.WHITE else "black",
                            "occurrences": 0,
                            "played_moves": Counter(),
                        }
                    buckets[fen]["occurrences"] += 1
                    buckets[fen]["played_moves"][move.uci()] += 1
                    
                board.push(move)
                node = next_node
                ply += 1
                
            positions = []
            for fen, bucket in buckets.items():
                board = chess.Board(fen)
                cached = db.position_evals.find_one({"_id": fen})
                if cached:
                    engine_result = AnalysisResult(**cached["result"])
                else:
                    engine_result = asyncio.run(analyzer_chain.analyze(board))
                    if engine_result:
                        db.position_evals.replace_one(
                            {"_id": fen},
                            {"result": engine_result.model_dump()},
                            upsert=True
                        )
                
                positions.append({
                    "fen": bucket["fen"],
                    "side_to_move": bucket["side_to_move"],
                    "occurrences": bucket["occurrences"],
                    "played_moves": dict(bucket["played_moves"].most_common()),
                    "engine": engine_result.model_dump() if engine_result else None,
                })
                
            positions.sort(key=lambda item: (-item["occurrences"], item["fen"]))
            
            mistakes = []
            for position in positions:
                engine = position["engine"]
                if not engine:
                    continue
                    
                board = chess.Board(position["fen"])
                best_move_uci = engine["best_move_uci"]
                best_score_value = engine.get("score_value")
                suboptimal_moves = []
                suboptimal_occurrences = 0
                
                for played_move_uci, count in position["played_moves"].items():
                    if played_move_uci == best_move_uci:
                        continue
                        
                    move = chess.Move.from_uci(played_move_uci)
                    move_cache_key = f"{position['fen']}|{played_move_uci}"
                    cached_move = db.position_evals.find_one({"_id": move_cache_key})
                    
                    if cached_move:
                        move_result = AnalysisResult(**cached_move["result"])
                    else:
                        move_result = asyncio.run(analyzer_chain.analyze(board, root_moves=[move]))
                        if move_result:
                            db.position_evals.replace_one(
                                {"_id": move_cache_key},
                                {"result": move_result.model_dump()},
                                upsert=True
                            )
                            
                    if not move_result:
                        continue
                        
                    score_loss = None
                    if best_score_value is not None and move_result.score_value is not None:
                        score_loss = best_score_value - move_result.score_value
                        
                    suboptimal_occurrences += count
                    suboptimal_moves.append({
                        "uci": played_move_uci,
                        "count": count,
                        "score": move_result.score.model_dump(),
                        "score_loss": score_loss,
                    })
                    
                if not suboptimal_moves:
                    continue
                    
                suboptimal_moves.sort(
                    key=lambda item: (-item["count"], -(item["score_loss"] or -1), item["uci"])
                )
                mistakes.append({
                    "fen": position["fen"],
                    "side_to_move": position["side_to_move"],
                    "occurrences": position["occurrences"],
                    "best_move_uci": best_move_uci,
                    "best_score": engine["score"],
                    "played_moves": position["played_moves"],
                    "suboptimal_occurrences": suboptimal_occurrences,
                    "suboptimal_moves": suboptimal_moves,
                })
                
            mistakes.sort(key=lambda item: (-item["occurrences"], item["fen"]))
            
            reports.append({
                "summary": {
                    "positions_seen": sum(item["occurrences"] for item in positions),
                    "unique_positions": len(positions),
                    "positions_with_suboptimal_moves": len(mistakes),
                },
                "positions": positions,
                "mistakes": mistakes,
            })
            
        db.review_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "completed", "reports": reports}}
        )
        log.info("task_review_opening_completed", job_id=job_id)
        
        # Clean up local temp file and Supabase storage
        try:
            if os.path.exists(local_temp_path):
                os.remove(local_temp_path)
            supabase.storage.from_(settings.SUPABASE_BUCKET).remove([object_key])
        except Exception as cleanup_err:
            log.warning("cleanup_failed", error=str(cleanup_err))
        
    except Exception as exc:
        log.error("task_review_opening_failed", job_id=job_id, error=str(exc), exc_info=True)
        db.review_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "failed", "error": str(exc)}}
        )
        # Clean up local temp file and Supabase storage on failure too
        try:
            if 'local_temp_path' in locals() and os.path.exists(local_temp_path):
                os.remove(local_temp_path)
            if 'object_key' in locals():
                supabase.storage.from_(settings.SUPABASE_BUCKET).remove([object_key])
        except Exception as cleanup_err:
            log.warning("cleanup_failed", error=str(cleanup_err))
            
        raise exc
