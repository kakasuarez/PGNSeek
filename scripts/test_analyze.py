import asyncio
import chess.pgn
from app.review.service import AnalyzerService
from app.config import settings

class DummyDB:
    pass

async def main():
    service = AnalyzerService(DummyDB())
    pgn = chess.pgn.Game()
    pgn.headers["White"] = "Hikaru"
    pgn.headers["Black"] = "Carlsen"
    pgn.headers["Result"] = "1-0"
    
    node = pgn.add_variation(chess.Move.from_uci("e2e4"))
    node = node.add_variation(chess.Move.from_uci("e7e5"))
    
    # patch analyze
    async def fake_analyze(board):
        class FakeResult:
            best_move_uci = "e2e4"
        return FakeResult()
    service.analyze = fake_analyze
    
    res = await service.analyze_game(pgn, "Hikaru")
    print(res)

asyncio.run(main())
