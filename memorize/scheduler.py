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
    def __init__(self, store: WordStore) -> None:
        self._store = store
        self._queue: deque[int] = deque()
        self._current_id: int | None = None
        self._peeked_id: int | None = None
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
        self._queue = deque(wid for wid in self._queue if wid != word_id)
        # Only refill if queue is empty AND no peek is pre-determined
        if not self._queue and self._peeked_id is None:
            self._fill_queue()

    def peek_next(self) -> dict | None:
        """Pre-determine the next word without advancing state. Idempotent."""
        if self._peeked_id is None:
            self._peeked_id = self._preview_next()
        return self._store.get_word(self._peeked_id) if self._peeked_id else None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _preview_next(self) -> int | None:
        """Non-destructive version of _pick_next: no popleft, no mark_introduced."""
        if self._queue:
            return self._queue[0]
        new_words = self._store.get_new_words(limit=1)
        if new_words:
            return new_words[0]["id"]
        candidates = self._store.get_lowest_stability_words(limit=10)
        candidates = [w for w in candidates if w["id"] != self._current_id]
        if candidates:
            return random.choice(candidates[: max(1, len(candidates) // 2)])["id"]
        return None

    def _pick_next(self) -> int | None:
        # Use pre-determined word if available
        if self._peeked_id is not None:
            word_id = self._peeked_id
            self._peeked_id = None
            self._queue = deque(wid for wid in self._queue if wid != word_id)
            word = self._store.get_word(word_id)
            if word and word.get("reps", 0) == 0:
                self._store.mark_introduced(word_id)
            return word_id

        # 1. Due words (real FSRS reviews)
        if self._queue:
            return self._queue.popleft()

        # 2. New words (no daily quota — user-paced)
        new_words = self._store.get_new_words(limit=1)
        if new_words:
            word_id = new_words[0]["id"]
            self._store.mark_introduced(word_id)
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
