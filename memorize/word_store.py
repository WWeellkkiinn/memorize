"""SQLite word repository with FSRS card state management."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

from fsrs import Card, Rating, ReviewLog as FsrsReviewLog, Scheduler

from memorize.config import FSRS_PARAMS_PATH

log = logging.getLogger(__name__)

# Legacy single-user data and the desktop app both live under this user id.
DEFAULT_USER_ID = 1


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

# owner_id partitions the dictionary per user: a word belongs to one user's
# library, so two users can own a same-spelling word with different definitions.
# owner_id IS NULL means a legacy/shared word that every user studies.
_CREATE_WORDS = """
CREATE TABLE IF NOT EXISTS words (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT NOT NULL,
    phonetic    TEXT NOT NULL DEFAULT '',
    pos         TEXT NOT NULL DEFAULT '',
    definition  TEXT NOT NULL DEFAULT '',
    examples    TEXT NOT NULL DEFAULT '[]',
    rank        INTEGER NOT NULL DEFAULT 0,
    morphemes   TEXT DEFAULT NULL,
    owner_id    INTEGER,
    UNIQUE(owner_id, word)
)
"""

# cards is keyed per-user: each (user_id, word_id) pair holds that user's FSRS state.
_CREATE_CARDS = """
CREATE TABLE IF NOT EXISTS cards (
    user_id            INTEGER NOT NULL DEFAULT 1,
    word_id            INTEGER NOT NULL REFERENCES words(id),
    fsrs_card          TEXT NOT NULL,
    due                TEXT NOT NULL,
    stability          REAL NOT NULL DEFAULT 0.0,
    reps               INTEGER NOT NULL DEFAULT 0,
    introduced_date    TEXT DEFAULT NULL,
    last_seen_at       TEXT DEFAULT NULL,
    PRIMARY KEY (user_id, word_id)
)
"""

_CREATE_REVIEW_LOGS = """
CREATE TABLE IF NOT EXISTS review_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL DEFAULT 1,
    word_id     INTEGER NOT NULL REFERENCES words(id),
    card_id     INTEGER NOT NULL DEFAULT 0,
    rating      INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    stability   REAL,
    difficulty  REAL
)
"""

_CREATE_IDX_DUE = "CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(user_id, due)"

# Shared SELECT fragment used by all word-listing queries. The cards JOIN is
# scoped to a user_id, so the first bound parameter of every query is the user.
_WORD_COLS = """
    SELECT w.id, w.word, w.phonetic, w.pos, w.definition, w.examples, w.morphemes,
           c.stability, c.reps, c.due
    FROM words w
    JOIN cards c ON c.word_id = w.id AND c.user_id = ?
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
        conn = sqlite3.connect(self._path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(_CREATE_WORDS)
            # Migration: words.rank / words.morphemes (must exist before the
            # owner_id rebuild copies them across).
            word_cols = {r[1] for r in conn.execute("PRAGMA table_info(words)")}
            if "rank" not in word_cols:
                conn.execute("ALTER TABLE words ADD COLUMN rank INTEGER NOT NULL DEFAULT 0")
            if "morphemes" not in word_cols:
                conn.execute("ALTER TABLE words ADD COLUMN morphemes TEXT DEFAULT NULL")
            self._migrate_cards(conn)
            self._migrate_review_logs(conn)
            conn.execute(_CREATE_IDX_DUE)
            conn.commit()
        # Runs on its own connection: the FK-safe table rebuild needs
        # foreign_keys OFF and must be outside any open transaction.
        self._migrate_words_owner()

    def _migrate_words_owner(self) -> None:
        """Add words.owner_id and switch uniqueness from `word` to `(owner_id, word)`.
        Legacy single-UNIQUE-word tables are rebuilt in place, preserving every id
        so cards/review_logs foreign keys stay valid; existing rows get owner_id NULL
        (shared). No-op once owner_id already exists."""
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.isolation_level = None  # autocommit, so we control BEGIN/COMMIT
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(words)")}
            if not cols or "owner_id" in cols:
                return
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN")
            conn.execute(
                "CREATE TABLE words_new ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " word TEXT NOT NULL,"
                " phonetic TEXT NOT NULL DEFAULT '',"
                " pos TEXT NOT NULL DEFAULT '',"
                " definition TEXT NOT NULL DEFAULT '',"
                " examples TEXT NOT NULL DEFAULT '[]',"
                " rank INTEGER NOT NULL DEFAULT 0,"
                " morphemes TEXT DEFAULT NULL,"
                " owner_id INTEGER,"
                " UNIQUE(owner_id, word))"
            )
            conn.execute(
                "INSERT INTO words_new(id, word, phonetic, pos, definition, examples, rank, morphemes, owner_id)"
                " SELECT id, word, phonetic, pos, definition, examples, rank, morphemes, NULL FROM words"
            )
            conn.execute("DROP TABLE words")
            conn.execute("ALTER TABLE words_new RENAME TO words")
            conn.execute("COMMIT")
            conn.execute("PRAGMA foreign_keys = ON")
            log.info("Migrated words: added owner_id; uniqueness now (owner_id, word)")
        finally:
            conn.close()

    def _migrate_cards(self, conn: sqlite3.Connection) -> None:
        """Create cards table, rebuilding the legacy single-user schema to a per-user one."""
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "cards" not in tables:
            conn.execute(_CREATE_CARDS)
            return
        card_cols = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
        if "user_id" in card_cols:
            return  # already migrated
        # Legacy schema: word_id is the sole PK and there is no user column.
        # Rebuild with the composite (user_id, word_id) PK and copy data under user 1.
        has_last_seen = "last_seen_at" in card_cols
        copy_cols = "word_id, fsrs_card, due, stability, reps, introduced_date"
        if has_last_seen:
            copy_cols += ", last_seen_at"
        conn.execute("ALTER TABLE cards RENAME TO cards_legacy")
        conn.execute(_CREATE_CARDS)
        conn.execute(
            f"INSERT INTO cards(user_id, {copy_cols}) SELECT 1, {copy_cols} FROM cards_legacy"
        )
        conn.execute("DROP TABLE cards_legacy")
        log.info("Migrated cards table to per-user schema (existing data → user 1)")

    def _migrate_review_logs(self, conn: sqlite3.Connection) -> None:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "review_logs" not in tables:
            conn.execute(_CREATE_REVIEW_LOGS)
            return
        cols = {r[1] for r in conn.execute("PRAGMA table_info(review_logs)")}
        if "card_id" not in cols:
            conn.execute("ALTER TABLE review_logs ADD COLUMN card_id INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE review_logs SET card_id = word_id WHERE card_id = 0")
        if "user_id" not in cols:
            conn.execute("ALTER TABLE review_logs ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

    # ── Per-user provisioning ──────────────────────────────────────────────────

    def delete_user_data(self, user_id: int) -> None:
        """Remove a user's per-user FSRS state (cards + review logs). Words are shared."""
        with self._conn() as conn:
            conn.execute("DELETE FROM cards WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM review_logs WHERE user_id=?", (user_id,))
            conn.commit()

    def init_cards_for_user(self, user_id: int) -> None:
        """Give a user a fresh FSRS card for every word in their own library that they
        don't have one for yet. A user's library is the words they own plus any legacy
        shared words (owner_id NULL); they never get cards for another user's words."""
        now = _now_utc()
        card_json = json.dumps(Card().to_dict())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards(user_id, word_id, fsrs_card, due, stability, reps)"
                " SELECT ?, id, ?, ?, 0.0, 0 FROM words WHERE owner_id = ? OR owner_id IS NULL",
                (user_id, card_json, _iso(now), user_id),
            )
            conn.commit()

    # ── Insert ────────────────────────────────────────────────────────────────

    def insert_word(
        self,
        word: str,
        phonetic: str = "",
        pos: str = "",
        definition: str = "",
        examples: list[dict] | None = None,
        rank: int = 0,
        owner_id: int | None = None,
    ) -> int | None:
        """Insert a word into a user's library (owner_id); return its id, or None if
        that user already owns it."""
        ex_json = json.dumps(examples or [], ensure_ascii=False)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO words(word, phonetic, pos, definition, examples, rank, owner_id)"
                " VALUES(?,?,?,?,?,?,?)",
                (word.lower(), phonetic, pos, definition, ex_json, rank, owner_id),
            )
            conn.commit()
            if cur.lastrowid and cur.rowcount:
                return cur.lastrowid
            row = conn.execute(
                "SELECT id FROM words WHERE word=? AND owner_id IS ?", (word.lower(), owner_id)
            ).fetchone()
            return row["id"] if row else None

    def init_card(self, word_id: int, user_id: int = DEFAULT_USER_ID) -> None:
        """Create a new FSRS card for (user_id, word_id) if one doesn't exist yet."""
        now = _now_utc()
        card = Card()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards(user_id, word_id, fsrs_card, due, stability, reps)"
                " VALUES(?,?,?,?,?,?)",
                (user_id, word_id, json.dumps(card.to_dict()), _iso(now), 0.0, 0),
            )
            conn.commit()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_due_words(self, limit: int = 20, user_id: int = DEFAULT_USER_ID) -> list[dict]:
        """Return words due for review (reps>0 only; new words go through get_new_words)."""
        now_str = _iso(_now_utc())
        with self._conn() as conn:
            rows = conn.execute(
                _WORD_COLS + "WHERE c.due <= ? AND c.reps > 0 ORDER BY c.due ASC LIMIT ?",
                (user_id, now_str, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_word(self, word_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT w.*, c.stability, c.reps, c.due FROM words w"
                " JOIN cards c ON c.word_id = w.id AND c.user_id = ? WHERE w.id=?",
                (user_id, word_id),
            ).fetchone()
        return dict(row) if row else None

    def get_new_words(self, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
        """Return words with reps=0 (never reviewed), ordered by frequency rank."""
        with self._conn() as conn:
            rows = conn.execute(
                _WORD_COLS + "WHERE c.reps = 0 ORDER BY RANDOM() LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_lowest_stability_words(self, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
        """Fallback: words with lowest stability (already reviewed at least once)."""
        with self._conn() as conn:
            rows = conn.execute(
                _WORD_COLS + "WHERE c.reps > 0 ORDER BY c.stability ASC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_introduced(self, word_id: int, user_id: int = DEFAULT_USER_ID) -> None:
        """Record today as the introduction date for a new word (idempotent)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE cards SET introduced_date=?"
                " WHERE user_id=? AND word_id=? AND introduced_date IS NULL",
                (_today(), user_id, word_id),
            )
            conn.commit()

    def get_random_word(self, exclude_id: int | None = None, user_id: int = DEFAULT_USER_ID) -> dict | None:
        """Return a reviewed word for passive display, biased toward low stability."""
        with self._conn() as conn:
            if exclude_id is not None:
                row = conn.execute(
                    _WORD_COLS + "WHERE c.reps > 0 AND w.id != ?"
                    " ORDER BY ABS(RANDOM()) / (c.stability + 1.5) DESC LIMIT 1",
                    (user_id, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    _WORD_COLS + "WHERE c.reps > 0"
                    " ORDER BY ABS(RANDOM()) / (c.stability + 1.5) DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
        return dict(row) if row else None

    def mark_seen(self, word_id: int, user_id: int = DEFAULT_USER_ID) -> None:
        """Record that this word was passively seen (does not affect FSRS)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE cards SET last_seen_at=? WHERE user_id=? AND word_id=?",
                (_iso(_now_utc()), user_id, word_id),
            )
            conn.commit()

    def get_preview_intervals(self, word_id: int, user_id: int = DEFAULT_USER_ID) -> dict[str, int]:
        """Preview next review intervals (days) for each rating without modifying state."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT fsrs_card FROM cards WHERE user_id=? AND word_id=?", (user_id, word_id)
            ).fetchone()
        if not row:
            return {"again": 1, "hard": 1, "good": 3, "easy": 7}
        now = _now_utc()
        fsrs_card_json = row["fsrs_card"]
        result = {}
        for rating, key in [
            (Rating.Again, "again"), (Rating.Hard, "hard"),
            (Rating.Good, "good"),  (Rating.Easy, "easy"),
        ]:
            card = Card.from_dict(json.loads(fsrs_card_json))
            new_card, _ = _fsrs.review_card(card, rating, now)
            result[key] = max(1, (new_card.due - now).days)
        return result

    def total_words(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM words").fetchone()
        return row["n"] if row else 0

    def get_progress(self, user_id: int = DEFAULT_USER_ID) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total,"
                " SUM(CASE WHEN introduced_date IS NOT NULL THEN 1 ELSE 0 END) AS introduced"
                " FROM cards WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return {"introduced": row["introduced"] or 0, "total": row["total"] or 0}

    def get_card_snapshot(self, word_id: int, user_id: int = DEFAULT_USER_ID) -> dict | None:
        """Return raw card fields for snapshotting before rate()."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT fsrs_card, due, stability, reps FROM cards WHERE user_id=? AND word_id=?",
                (user_id, word_id),
            ).fetchone()
        return dict(row) if row else None

    def undo_rate(self, word_id: int, snapshot: dict, user_id: int = DEFAULT_USER_ID) -> None:
        """Restore FSRS card state from snapshot (reverses one rate() call)."""
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "UPDATE cards SET fsrs_card=?, due=?, stability=?, reps=?"
                    " WHERE user_id=? AND word_id=?",
                    (snapshot["fsrs_card"], snapshot["due"], snapshot["stability"],
                     snapshot["reps"], user_id, word_id),
                )
                conn.execute(
                    "DELETE FROM review_logs WHERE id = ("
                    "  SELECT id FROM review_logs WHERE user_id=? AND word_id=?"
                    "  ORDER BY id DESC LIMIT 1)",
                    (user_id, word_id),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    # ── Review ────────────────────────────────────────────────────────────────

    def rate(self, word_id: int, rating: Rating, user_id: int = DEFAULT_USER_ID) -> None:
        """Apply FSRS rating and persist atomically (cards + review_logs)."""
        with self._conn() as conn:
            # IMMEDIATE lock: read + write in one atomic step
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT fsrs_card FROM cards WHERE user_id=? AND word_id=?", (user_id, word_id)
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    log.warning("rate() called for unknown word_id=%d user_id=%d", word_id, user_id)
                    return

                card = Card.from_dict(json.loads(row["fsrs_card"]))
                now = _now_utc()
                card, review_log = _fsrs.review_card(card, rating, now)

                conn.execute(
                    "UPDATE cards SET fsrs_card=?, due=?, stability=?, reps=reps+1"
                    " WHERE user_id=? AND word_id=?",
                    (json.dumps(card.to_dict()), _iso(card.due), card.stability, user_id, word_id),
                )
                conn.execute(
                    "INSERT INTO review_logs(user_id, word_id, card_id, rating, reviewed_at, stability, difficulty)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (user_id, word_id, review_log.card_id, rating.value, _iso(now),
                     card.stability, card.difficulty),
                )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def get_today_stats(self, user_id: int = DEFAULT_USER_ID) -> dict:
        now = datetime.now().astimezone()
        today = _today()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_start = _iso(day_start.astimezone(timezone.utc))
        utc_end = _iso((day_start + timedelta(days=1)).astimezone(timezone.utc))
        with self._conn() as conn:
            r = conn.execute(
                "SELECT"
                " COALESCE(SUM(CASE WHEN c.introduced_date=? THEN 1 END), 0) AS new_total,"
                " COUNT(DISTINCT CASE WHEN c.introduced_date=? THEN rl.word_id END) AS new_words,"
                " COALESCE(SUM(CASE WHEN c.introduced_date IS NULL OR c.introduced_date!=? THEN 1 END), 0) AS rev_total,"
                " COUNT(DISTINCT CASE WHEN c.introduced_date IS NULL OR c.introduced_date!=? THEN rl.word_id END) AS rev_words"
                " FROM review_logs rl"
                " LEFT JOIN cards c ON c.word_id = rl.word_id AND c.user_id = rl.user_id"
                " WHERE rl.user_id=? AND rl.reviewed_at>=? AND rl.reviewed_at<?",
                (today, today, today, today, user_id, utc_start, utc_end),
            ).fetchone()
        return {
            "newWords":      r["new_words"]  or 0,
            "newTotal":      r["new_total"]  or 0,
            "reviewedWords": r["rev_words"]  or 0,
            "reviewedTotal": r["rev_total"]  or 0,
        }

    def get_review_logs_for_optimizer(self, user_id: int = DEFAULT_USER_ID) -> list[FsrsReviewLog]:
        """Return all ReviewLog objects suitable for fsrs.Optimizer."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT card_id, rating, reviewed_at FROM review_logs"
                " WHERE user_id=? ORDER BY reviewed_at ASC",
                (user_id,),
            ).fetchall()
        return [
            FsrsReviewLog(
                card_id=r["card_id"],
                rating=Rating(r["rating"]),
                review_datetime=datetime.fromisoformat(r["reviewed_at"]),
            )
            for r in rows
        ]
