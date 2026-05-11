from __future__ import annotations

import base64
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fsrs import Rating
from pydantic import BaseModel, Field

from memorize.config import DB_PATH
from memorize.scheduler import WordScheduler
from memorize.word_store import WordStore

_AUTH_USER = os.environ.get("AUTH_USER", "")
_AUTH_PASS = os.environ.get("AUTH_PASS", "")

if not _AUTH_USER or not _AUTH_PASS:
    raise RuntimeError("AUTH_USER and AUTH_PASS environment variables must be set")

_STATIC = Path(__file__).parent / "static"
_UNAUTH = Response(
    status_code=401,
    headers={"WWW-Authenticate": 'Basic realm="memorize"'},
)


def _check_basic_auth(request: Request) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
        return secrets.compare_digest(username.encode(), _AUTH_USER.encode()) and \
               secrets.compare_digest(password.encode(), _AUTH_PASS.encode())
    except Exception:
        return False


def _compute_stage(word: dict) -> str:
    if word["reps"] == 0:
        return "新词"
    s = word["stability"]
    if s <= 1:
        return "初识"
    if s <= 7:
        return "记忆"
    if s <= 21:
        return "熟悉"
    return "掌握"


def _build_response(scheduler: WordScheduler, store: WordStore) -> dict:
    word = scheduler.current_word()
    stats = store.get_today_stats()
    if word:
        word = dict(word)
        word["stage"] = _compute_stage(word)
        intervals = store.get_preview_intervals(word["id"])
    else:
        intervals = None
    return {"word": word, "stats": stats, "intervals": intervals}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = WordStore(DB_PATH)
    scheduler = WordScheduler(store)
    app.state.store = store
    app.state.scheduler = scheduler
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if not _check_basic_auth(request):
        return _UNAUTH
    return await call_next(request)


app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/")
def root():
    return FileResponse(_STATIC / "index.html")


@app.get("/api/word")
def get_word():
    return _build_response(app.state.scheduler, app.state.store)


class RateRequest(BaseModel):
    word_id: int
    rating: int = Field(ge=1, le=4)


@app.post("/api/rate")
def rate_word(body: RateRequest):
    app.state.scheduler.rate(body.word_id, Rating(body.rating))
    return _build_response(app.state.scheduler, app.state.store)
