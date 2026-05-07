"""SQLite word repository with FSRS card state management."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from fsrs import Card, Rating, Scheduler

log = logging.getLogger(__name__)

_fsrs = Scheduler()

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
    introduced_date    TEXT NOT NULL DEFAULT (date('now'))
)
"""

_CREATE_REVIEW_LOGS = """
CREATE TABLE IF NOT EXISTS review_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id     INTEGER NOT NULL REFERENCES words(id),
    rating      INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    stability   REAL,
    difficulty  REAL
)
"""

_CREATE_IDX_DUE = "CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due)"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


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
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_CREATE_WORDS)
            conn.execute(_CREATE_CARDS)
            conn.execute(_CREATE_REVIEW_LOGS)
            conn.execute(_CREATE_IDX_DUE)
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
        card = Card()
        now = _now_utc()
        card_dict = card.to_dict()
        # new card is due immediately
        card_dict["due"] = _iso(now)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards(word_id, fsrs_card, due, stability, reps)"
                " VALUES(?,?,?,?,?)",
                (word_id, json.dumps(card_dict), _iso(now), 0.0, 0),
            )
            conn.commit()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_due_words(self, limit: int = 20) -> list[dict]:
        """Return words whose card is due now, ordered by due ASC."""
        now_str = _iso(_now_utc())
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT w.id, w.word, w.phonetic, w.pos, w.definition, w.examples,
                       c.stability, c.reps, c.due
                FROM words w
                JOIN cards c ON c.word_id = w.id
                WHERE c.due <= ?
                ORDER BY c.due ASC
                LIMIT ?
                """,
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
                """
                SELECT w.id, w.word, w.phonetic, w.pos, w.definition, w.examples,
                       c.stability, c.reps, c.due
                FROM words w
                JOIN cards c ON c.word_id = w.id
                WHERE c.reps = 0
                ORDER BY w.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_lowest_stability_words(self, limit: int = 5) -> list[dict]:
        """Fallback: words with lowest stability (already reviewed at least once)."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT w.id, w.word, w.phonetic, w.pos, w.definition, w.examples,
                       c.stability, c.reps, c.due
                FROM words w
                JOIN cards c ON c.word_id = w.id
                WHERE c.reps > 0
                ORDER BY c.stability ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_introduced_today(self) -> int:
        """Count words whose introduced_date is today (local date)."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM cards WHERE introduced_date=? AND reps=0",
                (today,),
            ).fetchone()
        return row["n"] if row else 0

    def total_words(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM words").fetchone()
        return row["n"] if row else 0

    # ── Review ────────────────────────────────────────────────────────────────

    def rate(self, word_id: int, rating: Rating) -> None:
        """Apply FSRS rating and persist atomically (cards + review_logs)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT fsrs_card FROM cards WHERE word_id=?", (word_id,)
            ).fetchone()
            if not row:
                log.warning("rate() called for unknown word_id=%d", word_id)
                return

            card = Card.from_dict(json.loads(row["fsrs_card"]))
            now = _now_utc()
            card, _ = _fsrs.review_card(card, rating, now)

            due_str = _iso(card.due)
            try:
                conn.execute("BEGIN")
                conn.execute(
                    "UPDATE cards SET fsrs_card=?, due=?, stability=?, reps=reps+1"
                    " WHERE word_id=?",
                    (json.dumps(card.to_dict()), due_str, card.stability, word_id),
                )
                conn.execute(
                    "INSERT INTO review_logs(word_id, rating, reviewed_at, stability, difficulty)"
                    " VALUES(?,?,?,?,?)",
                    (word_id, rating.value, _iso(now), card.stability, card.difficulty),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
