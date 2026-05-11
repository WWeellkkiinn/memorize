from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fsrs import Rating
from pydantic import BaseModel, Field

from memorize.config import DB_PATH
from memorize.scheduler import WordScheduler
from memorize.word_store import WordStore

_security = HTTPBasic()
_AUTH_USER = os.environ.get("AUTH_USER", "")
_AUTH_PASS = os.environ.get("AUTH_PASS", "")


def _require_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    ok = (
        secrets.compare_digest(credentials.username.encode(), _AUTH_USER.encode())
        and secrets.compare_digest(credentials.password.encode(), _AUTH_PASS.encode())
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

_STATIC = Path(__file__).parent / "static"


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
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", dependencies=[Depends(_require_auth)])
def root():
    return FileResponse(_STATIC / "index.html")


@app.get("/api/word", dependencies=[Depends(_require_auth)])
def get_word():
    return _build_response(app.state.scheduler, app.state.store)


class RateRequest(BaseModel):
    word_id: int
    rating: int = Field(ge=1, le=4)


@app.post("/api/rate", dependencies=[Depends(_require_auth)])
def rate_word(body: RateRequest):
    app.state.scheduler.rate(body.word_id, Rating(body.rating))
    return _build_response(app.state.scheduler, app.state.store)
