from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fsrs import Rating
from pydantic import BaseModel, Field

from memorize.config import DB_PATH
from memorize.scheduler import WordScheduler
from memorize.word_store import WordStore

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
