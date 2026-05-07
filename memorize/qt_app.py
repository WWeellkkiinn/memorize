"""Main Qt application orchestrator for Memorize."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

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
        self._scheduler = WordScheduler(self._store, self._config.daily_new_words)

        self._qt = QApplication.instance() or QApplication(sys.argv)
        self._qt.setQuitOnLastWindowClosed(False)

        self._bridge = BarBridge(self)
        self._bar = BarWindow(self._bridge, saved_x=self._config.bar_x,
                              on_ready=self._push_current_word)

        self._hover_active = False

        # ── Timers ────────────────────────────────────────────────────────────
        self._word_timer = QTimer()
        self._word_timer.setInterval(self._config.word_change_interval_sec * 1000)
        self._word_timer.timeout.connect(self._on_word_timer)

        self._remind_timer = QTimer()
        self._remind_timer.setInterval(self._config.reminder_interval_min * 60 * 1000)
        self._remind_timer.setSingleShot(False)
        self._remind_timer.timeout.connect(self._on_remind_timer)

        self._dismiss_timer = QTimer()
        self._dismiss_timer.setInterval(self._config.auto_dismiss_sec * 1000)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._on_dismiss_timer)

        # ── Primary screen change ─────────────────────────────────────────────
        QGuiApplication.instance().primaryScreenChanged.connect(self._on_screen_changed)

        # ── System tray ───────────────────────────────────────────────────────
        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("Memorize — 背单词")
        self._tray.setIcon(self._make_tray_icon())
        self._tray_menu = QMenu()           # kept as attribute to prevent GC
        self._tray_menu.addAction("退出").triggered.connect(self.quit)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.show()

        if self._config.passive_mode:
            self._word_timer.start()
        if self._config.active_mode:
            self._remind_timer.start()

    # ── Public methods (called by bridge) ─────────────────────────────────────

    def on_rated(self, word_id: int, rating_int: int) -> None:
        rating = _RATING_MAP.get(rating_int, Rating.Good)
        log.info("rated word_id=%d rating=%s", word_id, rating)
        self._scheduler.rate(word_id, rating)
        self._dismiss_timer.stop()
        self._hover_active = False
        self._advance_and_push()
        if self._config.passive_mode:
            self._word_timer.start()

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
        self._tray.hide()
        self._qt.quit()

    # ── Timer callbacks ───────────────────────────────────────────────────────

    def _on_word_timer(self) -> None:
        if self._hover_active:
            return  # don't change word while user is reading
        self._advance_and_push()

    def _on_remind_timer(self) -> None:
        if self._hover_active:
            return  # user is already looking at a word
        self._advance_and_push()
        self._bridge.expandTriggered.emit()
        self._dismiss_timer.start()

    def _on_dismiss_timer(self) -> None:
        self._bridge.collapseTriggered.emit()

    def _on_screen_changed(self) -> None:
        self._bar.reposition()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _push_current_word(self) -> None:
        word = self._scheduler.current_word()
        self._bridge.push_word(self._word_to_payload(word))

    def _advance_and_push(self) -> None:
        word = self._scheduler.advance()
        self._bridge.push_word(self._word_to_payload(word))

    @staticmethod
    def _word_to_payload(word: dict | None) -> dict:
        if not word:
            return {}
        return {
            "word_id": word.get("id", 0),
            "word": word.get("word", ""),
            "phonetic": word.get("phonetic", ""),
            "pos": word.get("pos", ""),
            "definition": word.get("definition", ""),
            "examples": word.get("examples", "[]"),
        }

    def run(self) -> int:
        return self._qt.exec()

    @staticmethod
    def _make_tray_icon() -> QIcon:
        """Create a simple 16x16 green 'M' icon for the system tray."""
        px = QPixmap(16, 16)
        px.fill(QColor(0, 0, 0, 0))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#10B981"))
        painter.setPen(QColor("#10B981"))
        painter.drawEllipse(1, 1, 14, 14)
        painter.setPen(QColor("#FFFFFF"))
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(px.rect(), 0x84, "M")  # AlignHCenter|AlignVCenter
        painter.end()
        return QIcon(px)
