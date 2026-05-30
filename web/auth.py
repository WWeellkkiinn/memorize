"""Web-only auth layer: users + server-side sessions, sharing the words.db SQLite file.

Kept separate from WordStore so the desktop app never needs argon2 or any auth code.
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

log = logging.getLogger(__name__)

SESSION_TTL = timedelta(days=30)
_ph = PasswordHasher()

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
)
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_IDX_SESSIONS = "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _user_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
    }


class AuthStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path, timeout=10.0)
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
            conn.execute(_CREATE_USERS)
            conn.execute(_CREATE_SESSIONS)
            conn.execute(_CREATE_IDX_SESSIONS)
            conn.commit()

    # ── Users ──────────────────────────────────────────────────────────────────

    def user_count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def create_user(
        self, email: str, password: str, display_name: str = "", is_admin: bool = False
    ) -> dict:
        """Create a user; raises ValueError if the email already exists."""
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("invalid email")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        pw_hash = _ph.hash(password)
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO users(email, password_hash, display_name, is_admin, created_at)"
                    " VALUES(?,?,?,?,?)",
                    (email, pw_hash, display_name or email.split("@")[0],
                     1 if is_admin else 0, _iso(_now())),
                )
                conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError("email already registered") from e
            row = conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        return _user_dict(row)

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return _user_dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY id ASC"
            ).fetchall()
        return [{**_user_dict(r), "created_at": r["created_at"]} for r in rows]

    def set_password(self, user_id: int, password: str) -> None:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        pw_hash = _ph.hash(password)
        with self._conn() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
            # Force re-login everywhere after a password change.
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.commit()

    def delete_user(self, user_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()

    def verify_login(self, email: str, password: str) -> dict | None:
        """Return the user dict on success, None on bad email/password."""
        email = email.strip().lower()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            return None
        try:
            _ph.verify(row["password_hash"], password)
        except VerifyMismatchError:
            return None
        except Exception as e:  # malformed hash etc.
            log.warning("password verify error for user %s: %s", email, e)
            return None
        return _user_dict(row)

    def ensure_admin(self, email: str, password: str) -> dict:
        """Create the admin from env if missing, or refresh its password if present."""
        email = email.strip().lower()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row:
            self.set_password(row["id"], password)
            with self._conn() as conn:
                conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
                conn.commit()
            return self.get_user_by_id(row["id"])  # type: ignore[return-value]
        return self.create_user(email, password, is_admin=True)

    # ── Sessions ───────────────────────────────────────────────────────────────

    def create_session(self, user_id: int) -> str:
        sid = secrets.token_urlsafe(32)
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions(id, user_id, expires_at, created_at) VALUES(?,?,?,?)",
                (sid, user_id, _iso(now + SESSION_TTL), _iso(now)),
            )
            conn.commit()
        return sid

    def get_session_user(self, session_id: str | None) -> dict | None:
        """Resolve a session cookie to its user, sliding the expiry forward on use."""
        if not session_id:
            return None
        now = _now()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT s.expires_at, u.* FROM sessions s"
                " JOIN users u ON u.id = s.user_id WHERE s.id=?",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            if datetime.fromisoformat(row["expires_at"]) < now:
                conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                conn.commit()
                return None
            # Rolling renewal: extend the window on activity.
            conn.execute(
                "UPDATE sessions SET expires_at=? WHERE id=?",
                (_iso(now + SESSION_TTL), session_id),
            )
            conn.commit()
        return _user_dict(row)

    def delete_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            conn.commit()

    def purge_expired(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(_now()),))
            conn.commit()
