"""HTTP-based scheduler: mirrors WordScheduler's public interface, calls server REST API."""
from __future__ import annotations

import base64
import json
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from fsrs import Rating

log = logging.getLogger(__name__)


class RemoteScheduler:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._base = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._auth = f"Basic {token}"
        self._current: dict | None = None
        self._next: dict | None = None
        self._stats: dict = {}

    @property
    def current_word_id(self) -> int | None:
        return self._current["id"] if self._current else None

    def current_word(self) -> dict | None:
        if self._current is None:
            data = self._get("/api/word")
            self._current = data.get("word")
            self._stats = data.get("stats") or {}
        return self._current

    def advance(self) -> dict | None:
        if self._next is not None:
            self._current = self._next
            self._next = None
            return self._current
        data = self._get("/api/word")
        self._current = data.get("word")
        self._stats = data.get("stats") or {}
        return self._current

    def rate(self, word_id: int, rating: Rating) -> None:
        data = self._post("/api/rate", {"word_id": word_id, "rating": rating.value})
        if not data:
            return  # POST failed; keep current state, advance() will fetch /api/word
        self._current = None
        self._next = data.get("word")
        self._stats = data.get("stats") or {}

    def peek_next(self) -> dict | None:
        data = self._get("/api/peek")
        return data.get("word")

    def get_today_stats(self) -> dict:
        return self._stats

    # ── Internal ─────────────────────────────────────────────────────────────

    def _request(self, req: Request) -> dict:
        try:
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except (URLError, OSError, ValueError) as e:
            log.warning("RemoteScheduler %s %s failed: %s", req.get_method(), req.full_url, e)
            return {}

    def _get(self, path: str) -> dict:
        req = Request(self._base + path, headers={"Authorization": self._auth})
        return self._request(req)

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = Request(
            self._base + path, data=data,
            headers={"Authorization": self._auth, "Content-Type": "application/json"},
        )
        return self._request(req)
