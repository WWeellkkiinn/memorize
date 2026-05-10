"""Main Qt application orchestrator for Memorize."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from fsrs import Rating

from memorize.config import DB_PATH, LOG_PATH, load_config, save_config
from memorize.scheduler import WordScheduler
from memorize.ui.bar_bridge import BarBridge
from memorize.ui.bar_window import BarWindow
from memorize.word_store import WordStore

log = logging.getLogger(__name__)

_RATING_MAP = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


class MemorizeApp:
    def __init__(self) -> None:
        _setup_logging()

        self._config = load_config()
        self._store = WordStore(DB_PATH)
        self._scheduler = WordScheduler(self._store)

        self._qt = QApplication.instance() or QApplication(sys.argv)
        self._qt.setQuitOnLastWindowClosed(False)

        self._bridge = BarBridge(self)
        self._bar = BarWindow(self._bridge, saved_x=self._config.bar_x,
                              on_ready=self._push_current_word)

        self._hover_active = False
        self._passive_word_id: int | None = None

        # ── Timers ────────────────────────────────────────────────────────────
        self._word_timer = QTimer()
        self._word_timer.setInterval(self._config.word_change_interval_sec * 1000)
        self._word_timer.timeout.connect(self._on_word_timer)

        # ── Primary screen change ─────────────────────────────────────────────
        QGuiApplication.instance().primaryScreenChanged.connect(self._on_screen_changed)

        # Timers start in _push_current_word (on_ready) so they never
        # fire before the first word has been pushed to QML.

    # ── Public methods (called by bridge) ─────────────────────────────────────

    def on_rated(self, word_id: int, rating_int: int) -> None:
        rating = _RATING_MAP.get(rating_int, Rating.Good)
        log.info("rated word_id=%d rating=%s", word_id, rating)
        self._scheduler.rate(word_id, rating)
        self._advance_and_push()
        # Card stays open; hover state and timers managed by hover enter/leave

    def on_hover_enter(self) -> None:
        self._hover_active = True
        self._word_timer.stop()

    def on_hover_leave(self) -> None:
        self._hover_active = False
        if self._config.passive_mode:
            self._word_timer.start()

    def remember_bar_x(self, x: int) -> None:
        self._config.bar_x = x
        save_config(self._config)

    def quit(self) -> None:
        self._qt.quit()

    # ── Timer callbacks ───────────────────────────────────────────────────────

    def _on_word_timer(self) -> None:
        if self._hover_active:
            return
        self._push_passive_word()

    def _on_screen_changed(self) -> None:
        self._bar.reposition()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _push_current_word(self) -> None:
        word = self._scheduler.current_word()
        self._bridge.push_word(self._word_to_payload(word, self._store.get_today_stats()))
        self._push_passive_word()
        if self._config.passive_mode:
            self._word_timer.start()

    def _push_passive_word(self) -> None:
        word = self._store.get_random_word(exclude_id=self._passive_word_id)
        if word:
            if self._passive_word_id is not None:
                self._store.mark_seen(self._passive_word_id)
            self._passive_word_id = word["id"]
            self._bridge.push_passive_word(self._word_to_payload(word))

    def _advance_and_push(self) -> None:
        word = self._scheduler.advance()
        self._bridge.push_word(self._word_to_payload(word, self._store.get_today_stats()))

    @staticmethod
    def _retention_pct(word: dict) -> int:
        reps = word.get("reps", 0)
        stability = word.get("stability", 0.0)
        due_str = word.get("due", "")
        if reps == 0 or stability <= 0 or not due_str:
            return -1
        try:
            due_dt = datetime.fromisoformat(due_str)
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            elapsed_days = max(0.0, stability + (now - due_dt).total_seconds() / 86400)
            r = (1 + (19 / 81) * elapsed_days / stability) ** -0.5
            return round(r * 100)
        except (ValueError, TypeError):
            return -1

    @staticmethod
    def _word_to_payload(word: dict | None, stats: dict | None = None) -> dict:
        payload: dict = {}
        if word:
            payload = {
                "word_id": word.get("id", 0),
                "word": word.get("word", ""),
                "phonetic": word.get("phonetic", ""),
                "pos": word.get("pos", ""),
                "definition": word.get("definition", ""),
                "examples": word.get("examples", "[]"),
                "retentionPct": MemorizeApp._retention_pct(word),
            }
        if stats:
            payload["todayNew"]           = stats["newWords"]
            payload["todayNewTotal"]      = stats["newTotal"]
            payload["todayReviewed"]      = stats["reviewedWords"]
            payload["todayReviewedTotal"] = stats["reviewedTotal"]
        return payload

    def run(self) -> int:
        return self._qt.exec()

