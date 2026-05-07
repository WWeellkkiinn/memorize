"""Word scheduling: FSRS-driven queue with passive rotation and active reminder support."""
from __future__ import annotations

import logging
import random
from collections import deque
from datetime import datetime

from fsrs import Rating

from memorize.word_store import WordStore

log = logging.getLogger(__name__)

# How many due words to load into the in-memory queue at once
_QUEUE_FILL = 20


class WordScheduler:
    def __init__(self, store: WordStore, daily_new_words: int = 20) -> None:
        self._store = store
        self._daily_new_words = daily_new_words

        # Queue of word_id ints for upcoming passive display
        self._queue: deque[int] = deque()
        # word_id currently shown on the bar (may be None if not started yet)
        self._current_id: int | None = None
        # Tracks whether the current word is a "fallback" (not a real due review)
        self._current_is_fallback: bool = False

        self._fill_queue()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def current_word_id(self) -> int | None:
        return self._current_id

    @property
    def current_is_fallback(self) -> bool:
        return self._current_is_fallback

    def advance(self) -> dict | None:
        """Move to the next word. Returns the word dict or None if library is empty."""
        word_id = self._pick_next_id()
        if word_id is None:
            self._current_id = None
            self._current_is_fallback = False
            return None
        self._current_id = word_id
        return self._store.get_word(word_id)

    def current_word(self) -> dict | None:
        """Return the currently displayed word dict, or advance if none set."""
        if self._current_id is None:
            return self.advance()
        return self._store.get_word(self._current_id)

    def rate(self, word_id: int, rating: Rating) -> None:
        """Apply FSRS rating and refresh queue."""
        if self._current_is_fallback:
            # Fallback words are shown for passive exposure only; ratings are still recorded
            # so the FSRS schedule can be properly initialized.
            pass
        self._store.rate(word_id, rating)
        self._fill_queue()

    def refresh(self) -> None:
        """Reload the queue from DB (call after external DB changes)."""
        self._fill_queue()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _pick_next_id(self) -> int | None:
        # 1. Due words (real FSRS reviews)
        if self._queue:
            self._current_is_fallback = False
            return self._queue.popleft()

        # 2. New words (if daily quota not exhausted)
        if self._store.count_introduced_today() < self._daily_new_words:
            new = self._store.get_new_words(limit=1)
            if new:
                self._current_is_fallback = False
                return new[0]["id"]

        # 3. Fallback: lowest-stability already-reviewed word
        fallback = self._store.get_lowest_stability_words(limit=5)
        if fallback:
            self._current_is_fallback = True
            # Shuffle slightly so the same word isn't shown repeatedly
            return random.choice(fallback)["id"]

        return None

    def _fill_queue(self) -> None:
        due = self._store.get_due_words(limit=_QUEUE_FILL)
        existing = set(self._queue)
        for row in due:
            wid = row["id"]
            if wid not in existing and wid != self._current_id:
                self._queue.append(wid)
