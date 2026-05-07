"""SQLite word repository with FSRS card state management."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from fsrs import Card, Rating, ReviewLog as FsrsReviewLog, Scheduler

from memorize.config import FSRS_PARAMS_PATH

log = logging.getLogger(__name__)


def _load_scheduler() -> Scheduler:
    try:
        if FSRS_PARAMS_PATH.exists():
            params = json.loads(FSRS_PARAMS_PATH.read_text(encoding="utf-8"))
            log.info("Loaded custom FSRS parameters from %s", FSRS_PARAMS_PATH)
            return Scheduler(parameters=params)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.warning("Invalid fsrs_params.json, using defaults: %s", e)
    return Scheduler()


_fsrs = _load_scheduler()

_CREATE_WORDS = """
CREATE TABLE IF NOT EXISTS words (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT UNIQUE NOT NULL,
    phonetic    TEXT NOT NULL DEFAULT '',
    pos         TEXT NOT NULL DEFAULT '',
    definition  TEXT NOT NULL DEFAULT '',
    examples    TEXT NOT NULL DEFAULT '[]'
)
"""

_CREATE_CARDS = """
CREATE TABLE IF NOT EXISTS cards (
    word_id            INTEGER PRIMARY KEY REFERENCES words(id),
    fsrs_card          TEXT NOT NULL,
    due                TEXT NOT NULL,
    stability          REAL NOT NULL DEFAULT 0.0,
    reps               INTEGER NOT NULL DEFAULT 0,
    introduced_date    TEXT DEFAULT NULL
)
"""

_CREATE_REVIEW_LOGS = """
CREATE TABLE IF NOT EXISTS review_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id     INTEGER NOT NULL REFERENCES words(id),
    card_id     INTEGER NOT NULL DEFAULT 0,
    rating      INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    stability   REAL,
    difficulty  REAL
)
"""

_CREATE_IDX_DUE = "CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due)"

# Shared SELECT fragment used by all word-listing queries
_WORD_COLS = """
    SELECT w.id, w.word, w.phonetic, w.pos, w.definition, w.examples,
           c.stability, c.reps, c.due
    FROM words w
    JOIN cards c ON c.word_id = w.id
"""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class WordStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(_CREATE_WORDS)
            conn.execute(_CREATE_CARDS)
            conn.execute(_CREATE_REVIEW_LOGS)
            conn.execute(_CREATE_IDX_DUE)
            # Migration: add card_id column and back-fill with word_id for old rows
            cols = {r[1] for r in conn.execute("PRAGMA table_info(review_logs)")}
            if "card_id" not in cols:
                conn.execute("ALTER TABLE review_logs ADD COLUMN card_id INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE review_logs SET card_id = word_id WHERE card_id = 0")
            conn.commit()

    # ── Insert ────────────────────────────────────────────────────────────────

    def insert_word(
        self,
        word: str,
        phonetic: str = "",
        pos: str = "",
        definition: str = "",
        examples: list[dict] | None = None,
    ) -> int | None:
        """Insert a word; return its id, or None if it already exists."""
        ex_json = json.dumps(examples or [], ensure_ascii=False)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO words(word, phonetic, pos, definition, examples)"
                " VALUES(?,?,?,?,?)",
                (word.lower(), phonetic, pos, definition, ex_json),
            )
            conn.commit()
            if cur.lastrowid and cur.rowcount:
                return cur.lastrowid
            row = conn.execute("SELECT id FROM words WHERE word=?", (word.lower(),)).fetchone()
            return row["id"] if row else None

    def init_card(self, word_id: int) -> None:
        """Create a new FSRS card for word_id if one doesn't exist yet."""
        now = _now_utc()
        card = Card()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards(word_id, fsrs_card, due, stability, reps)"
                " VALUES(?,?,?,?,?)",
                (word_id, json.dumps(card.to_dict()), _iso(now), 0.0, 0),
            )
            conn.commit()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_due_words(self, limit: int = 20) -> list[dict]:
        """Return words due for review (reps>0 only; new words go through get_new_words)."""
        now_str = _iso(_now_utc())
        with self._conn() as conn:
            rows = conn.execute(
                _WORD_COLS + "WHERE c.due <= ? AND c.reps > 0 ORDER BY c.due ASC LIMIT ?",
                (now_str, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_word(self, word_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT w.*, c.stability, c.reps, c.due FROM words w"
                " JOIN cards c ON c.word_id = w.id WHERE w.id=?",
                (word_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_new_words(self, limit: int = 5) -> list[dict]:
        """Return words with reps=0 (never reviewed), for new-word introduction."""
        with self._conn() as conn:
            rows = conn.execute(
                _WORD_COLS + "WHERE c.reps = 0 ORDER BY w.id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_lowest_stability_words(self, limit: int = 5) -> list[dict]:
        """Fallback: words with lowest stability (already reviewed at least once)."""
        with self._conn() as conn:
            rows = conn.execute(
                _WORD_COLS + "WHERE c.reps > 0 ORDER BY c.stability ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_introduced(self, word_id: int) -> None:
        """Record today as the introduction date for a new word (idempotent)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE cards SET introduced_date=? WHERE word_id=? AND introduced_date IS NULL",
                (_today(), word_id),
            )
            conn.commit()

    def total_words(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM words").fetchone()
        return row["n"] if row else 0

    # ── Review ────────────────────────────────────────────────────────────────

    def rate(self, word_id: int, rating: Rating) -> None:
        """Apply FSRS rating and persist atomically (cards + review_logs)."""
        with self._conn() as conn:
            # IMMEDIATE lock: read + write in one atomic step
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT fsrs_card FROM cards WHERE word_id=?", (word_id,)
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    log.warning("rate() called for unknown word_id=%d", word_id)
                    return

                card = Card.from_dict(json.loads(row["fsrs_card"]))
                now = _now_utc()
                card, review_log = _fsrs.review_card(card, rating, now)

                conn.execute(
                    "UPDATE cards SET fsrs_card=?, due=?, stability=?, reps=reps+1"
                    " WHERE word_id=?",
                    (json.dumps(card.to_dict()), _iso(card.due), card.stability, word_id),
                )
                conn.execute(
                    "INSERT INTO review_logs(word_id, card_id, rating, reviewed_at, stability, difficulty)"
                    " VALUES(?,?,?,?,?,?)",
                    (word_id, review_log.card_id, rating.value, _iso(now), card.stability, card.difficulty),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def get_review_logs_for_optimizer(self) -> list[FsrsReviewLog]:
        """Return all ReviewLog objects suitable for fsrs.Optimizer."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT card_id, rating, reviewed_at FROM review_logs ORDER BY reviewed_at ASC"
            ).fetchall()
        return [
            FsrsReviewLog(
                card_id=r["card_id"],
                rating=Rating(r["rating"]),
                review_datetime=datetime.fromisoformat(r["reviewed_at"]),
            )
            for r in rows
        ]
