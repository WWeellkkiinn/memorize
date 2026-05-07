"""QObject bridge between Python business logic and QML UI."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class BarBridge(QObject):
    # Python → QML
    wordChanged = Signal("QVariantMap")        # active (FSRS) word
    passiveWordChanged = Signal("QVariantMap") # passive bar word
    expandTriggered = Signal()
    collapseTriggered = Signal()
    maskHeightChanged = Signal(int)
    moveWindowX = Signal(int)
    commitWindowX = Signal(int)

    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self._app = app

    def push_word(self, word: dict | None) -> None:
        self.wordChanged.emit(word or {})

    def push_passive_word(self, word: dict | None) -> None:
        self.passiveWordChanged.emit(word or {})

    # ── QML → Python ─────────────────────────────────────────────────────────

    @Slot(int, int)
    def rate(self, word_id: int, rating_int: int) -> None:
        self._app.on_rated(word_id, rating_int)

    @Slot()
    def onHoverEnter(self) -> None:
        self._app.on_hover_enter()

    @Slot()
    def onHoverLeave(self) -> None:
        self._app.on_hover_leave()

    @Slot(float)
    def moveBarX(self, x: float) -> None:
        self.moveWindowX.emit(int(x))

    @Slot(float)
    def saveBarX(self, x: float) -> None:
        self.commitWindowX.emit(int(x))

    def commit_bar_x(self, x: int) -> None:
        self._app.remember_bar_x(x)

    @Slot(float)
    def setVisibleHeight(self, h: float) -> None:
        self.maskHeightChanged.emit(int(h))

    @Slot()
    def quit(self) -> None:
        self._app.quit()
