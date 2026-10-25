"""
Tests for the review position store and the position endpoints.

Run from backend/: venv/bin/python -m pytest app/tests
"""

import asyncio
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock

import chess
import chess.pgn
import pytest
from fastapi.testclient import TestClient

import app.api.review as review_api
import app.review.store as store
from app.db import get_db
from app.main import app
from app.review.report import ReviewReportBuilder, normalize_fen
from app.tests.fake_mongo import FakeDB

JOB_ID = "11111111-1111-1111-1111-111111111111"
EXPIRES_AT = datetime(2026, 11, 1, tzinfo=timezone.utc)
START = normalize_fen(chess.Board())


def fen_after(*uci_moves: str) -> str:
    board = chess.Board()
    for uci in uci_moves:
        board.push_uci(uci)
    return normalize_fen(board)


def build_tree(*games: str) -> ReviewReportBuilder:
    builder = ReviewReportBuilder("me", max_plies=6)
    for moves in games:
        game = chess.pgn.read_game(io.StringIO(f'[White "me"]\n[Black "them"]\n[Result "1-0"]\n\n{moves} 1-0'))
        assert game is not None
        builder.add_game(game)
    return builder


def saved_db(builder: ReviewReportBuilder, tree_id: str = JOB_ID) -> FakeDB:
    db = FakeDB()
    asyncio.run(store.save_positions(db, tree_id, builder.positions(), EXPIRES_AT))  # type: ignore[arg-type]
    return db


# -- Store ---------------------------------------------------------------------


def test_save_positions_stores_one_document_per_position():
    builder = build_tree("1. e4 e5 2. Nf3", "1. d4 d5")
    db = saved_db(builder)
    documents = db["review_positions"].documents

    assert len(documents) == len(list(builder.positions()))
    start = next(d for d in documents if d["fen"] == START)
    assert start["tree_id"] == JOB_ID
    assert start["color"] == "white"
    assert start["expires_at"] == EXPIRES_AT
    assert start["played_moves"] == {"e2e4": {"count": 1}, "d2d4": {"count": 1}}
    assert "line" not in start


def test_save_positions_without_expiry_never_expires():
    db = FakeDB()
    asyncio.run(store.save_positions(db, "lichess:me", build_tree("1. e4").positions(), None))  # type: ignore[arg-type]
    assert all("expires_at" not in d for d in db["review_positions"].documents)


def test_save_positions_replaces_only_its_own_tree(monkeypatch):
    monkeypatch.setattr(store, "WRITE_BATCH_SIZE", 2)  # exercise several batches
    db = saved_db(build_tree("1. e4 e5 2. Nf3 Nc6"), tree_id="other-job")
    first = asyncio.run(store.save_positions(db, JOB_ID, build_tree("1. e4 e5 2. Nf3 Nc6").positions(), EXPIRES_AT))  # type: ignore[arg-type]
    second = asyncio.run(store.save_positions(db, JOB_ID, build_tree("1. d4").positions(), EXPIRES_AT))  # type: ignore[arg-type]

    assert first == 4 and second == 1
    trees = [d["tree_id"] for d in db["review_positions"].documents]
    assert trees.count(JOB_ID) == 1  # the retried job's old tree is gone
    assert trees.count("other-job") == 4


def test_child_fens_are_most_played_first_and_capped():
    builder = build_tree("1. e4", "1. e4", "1. d4", "1. c4", "1. Nf3", "1. Nf3", "1. Nf3")
    start = builder.repertoires["white"]["positions"][START]
    assert store.child_fens(start, limit=2) == [fen_after("g1f3"), fen_after("e2e4")]
    assert len(store.child_fens(start)) == 4


def test_get_position_with_children():
    db = saved_db(build_tree("1. e4 e5 2. Nf3", "1. e4 c5"))
    position, children = asyncio.run(store.get_position_with_children(db, JOB_ID, "white", fen_after("e2e4")))  # type: ignore[arg-type]

    assert position is not None and position["fen"] == fen_after("e2e4")
    # 1...c5 ended that game, so no move was played from it and it isn't stored
    assert [c["fen"] for c in children] == [fen_after("e2e4", "e7e5")]
    assert list(children[0]["played_moves"]) == ["g1f3"]
    assert all({"_id", "tree_id", "expires_at"}.isdisjoint(c) for c in [position, *children])


def test_get_position_with_children_unknown_position():
    db = saved_db(build_tree("1. e4 e5"))
    assert asyncio.run(store.get_position_with_children(db, JOB_ID, "white", fen_after("d2d4"))) == (None, [])  # type: ignore[arg-type]
    assert asyncio.run(store.get_position_with_children(db, JOB_ID, "black", START)) == (None, [])  # type: ignore[arg-type]


# -- API -----------------------------------------------------------------------


@pytest.fixture
def client():
    db = saved_db(build_tree("1. e4 e5 2. Nf3 Nc6", "1. e4 c5 2. Nf3"))
    asyncio.run(db.review_jobs.insert_one({"_id": JOB_ID, "status": "completed", "report": {"summary": {}}}))
    asyncio.run(db.review_jobs.insert_one({"_id": "22222222-2222-2222-2222-222222222222", "status": "running"}))
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), db
    app.dependency_overrides.clear()


def test_get_position_endpoint(client):
    http, _ = client
    # Full six-field FENs are accepted and normalized
    res = http.get(f"/api/v1/review/{JOB_ID}/positions", params={"color": "white", "fen": chess.STARTING_FEN})
    assert res.status_code == 200
    body = res.json()
    assert body["position"]["fen"] == START
    assert body["position"]["occurrences"] == 2
    assert [c["fen"] for c in body["children"]] == [fen_after("e2e4")]


def test_get_position_endpoint_unreached_position(client):
    http, _ = client
    res = http.get(f"/api/v1/review/{JOB_ID}/positions", params={"color": "white", "fen": fen_after("a2a3")})
    assert res.status_code == 200
    assert res.json() == {"position": None, "children": []}


def test_batch_endpoint_returns_found_positions(client):
    http, _ = client
    fens = [START, fen_after("e2e4"), fen_after("e2e4", "e7e5"), fen_after("h2h4")]
    res = http.post(f"/api/v1/review/{JOB_ID}/positions/batch", json={"color": "white", "fens": fens})
    assert res.status_code == 200
    assert sorted(res.json()["positions"]) == sorted(fens[:3])


@pytest.mark.parametrize(
    "method, path, kwargs, status",
    [
        ("get", "/api/v1/review/{job}/positions", {"params": {"color": "white", "fen": "not a fen"}}, 422),
        ("get", "/api/v1/review/{job}/positions", {"params": {"color": "red", "fen": START}}, 422),
        ("post", "/api/v1/review/{job}/positions/batch", {"json": {"color": "white", "fens": [START] * 65}}, 422),
        ("get", "/api/v1/review/33333333-3333-3333-3333-333333333333/positions", {"params": {"color": "white", "fen": START}}, 404),
        ("get", "/api/v1/review/22222222-2222-2222-2222-222222222222/positions", {"params": {"color": "white", "fen": START}}, 400),
    ],
)
def test_position_endpoint_errors(client, method, path, kwargs, status):
    http, _ = client
    res = getattr(http, method)(path.format(job=JOB_ID), **kwargs)
    assert res.status_code == status


def test_submitted_job_gets_an_expiry(client, monkeypatch):
    http, db = client
    monkeypatch.setattr(review_api, "supabase", MagicMock())
    monkeypatch.setattr(review_api, "review_opening", MagicMock())
    res = http.post("/api/v1/review", files={"pgn_file": ("g.pgn", b"1. e4 *")}, data={"player": "me"})
    assert res.status_code == 200

    job = asyncio.run(db.review_jobs.find_one({"_id": str(res.json()["job_id"])}))
    remaining = (job["expires_at"] - datetime.now(timezone.utc)).total_seconds()
    assert job["status"] == "queued"
    assert 604_700 < remaining <= 604_800
