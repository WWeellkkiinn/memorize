"""Word scheduling: FSRS-driven queue with passive rotation and active reminder support."""
from __future__ import annotations

import logging
import random
from collections import deque

from fsrs import Rating

from memorize.word_store import WordStore

log = logging.getLogger(__name__)

_QUEUE_FILL = 20


class WordScheduler:
    def __init__(self, store: WordStore, daily_new_words: int = 20) -> None:
        self._store = store
        self._daily_new_words = daily_new_words
        self._queue: deque[int] = deque()
        self._current_id: int | None = None
        # Cache today's new-word count to avoid a DB query on every advance
        self._introduced_today: int = store.count_introduced_today()
        self._fill_queue()

    @property
    def current_word_id(self) -> int | None:
        return self._current_id

    def advance(self) -> dict | None:
        """Move to the next word. Returns the word dict or None if library is empty."""
        word_id = self._pick_next()
        self._current_id = word_id
        if word_id is None:
            return None
        return self._store.get_word(word_id)

    def current_word(self) -> dict | None:
        """Return the currently displayed word dict, advancing if none set yet."""
        if self._current_id is None:
            return self.advance()
        word = self._store.get_word(self._current_id)
        if word is None:
            return self.advance()
        return word

    def rate(self, word_id: int, rating: Rating) -> None:
        """Apply FSRS rating and update the queue without a full DB rebuild."""
        self._store.rate(word_id, rating)
        if self._current_id == word_id:
            self._current_id = None
        # Remove the rated word from the in-memory queue; refill only if empty
        self._queue = deque(wid for wid in self._queue if wid != word_id)
        if not self._queue:
            self._fill_queue()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _pick_next(self) -> int | None:
        # 1. Due words (real FSRS reviews)
        if self._queue:
            return self._queue.popleft()

        # 2. New words (if daily quota not exhausted)
        if self._introduced_today < self._daily_new_words:
            new_words = self._store.get_new_words(limit=1)
            if new_words:
                word_id = new_words[0]["id"]
                self._store.mark_introduced(word_id)
                self._introduced_today += 1
                return word_id

        # 3. Fallback: lowest-stability already-reviewed word (exclude current)
        candidates = self._store.get_lowest_stability_words(limit=10)
        candidates = [w for w in candidates if w["id"] != self._current_id]
        if candidates:
            pick_from = candidates[: max(1, len(candidates) // 2)]
            return random.choice(pick_from)["id"]

        return None

    def _fill_queue(self) -> None:
        """Rebuild the in-memory due queue from DB."""
        due = self._store.get_due_words(limit=_QUEUE_FILL)
        seen: set[int] = set()
        new_queue: deque[int] = deque()
        for row in due:
            wid = row["id"]
            if wid != self._current_id and wid not in seen:
                new_queue.append(wid)
                seen.add(wid)
        self._queue = new_queue
