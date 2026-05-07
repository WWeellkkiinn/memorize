"""Qt window management for the Memorize bottom bar."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from memorize.ui.win32_bar import set_bottom_bar_mask, setup_toolwindow

_QT6_QML_DIR = os.path.join(os.path.dirname(PySide6.__file__), "Qt6", "qml")
_QML_PATH = Path(__file__).with_name("bar.qml")

_BASE_BAR_W = 360
_BASE_BAR_H = 24


def _primary_ag():
    """Primary screen available geometry as (x, y, w, h) in Qt logical pixels."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 0, 0, 1920, 1080
    ag = screen.availableGeometry()
    return ag.x(), ag.y(), ag.width(), ag.height()


def _get_ui_scale() -> float:
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        win_scale = max(dpi, 96) / 96.0
        return 1.0 + (win_scale - 1.0) * 0.5
    except Exception:
        return 1.0


class BarWindow:
    def __init__(self, bridge, saved_x: int | None = None, on_ready=None) -> None:
        self._bridge = bridge
        self._saved_x = saved_x
        self._own_hwnd = 0
        self._pending_visible_h: int = 0
        self._on_ready = on_ready

        sf = _get_ui_scale()
        self._bar_w = int(_BASE_BAR_W * sf)
        self._bar_h = int(_BASE_BAR_H * sf)

        self._engine = QQmlApplicationEngine()
        if os.path.isdir(_QT6_QML_DIR):
            self._engine.addImportPath(_QT6_QML_DIR)
        ctx = self._engine.rootContext()
        ctx.setContextProperty("bridge", bridge)
        ctx.setContextProperty("scaleFactor", float(sf))
        self._engine.load(str(_QML_PATH))

        roots = self._engine.rootObjects()
        if not roots:
            print("[Memorize] QML failed to load", file=sys.stderr)
            sys.exit(1)
        self._win = roots[0]

        self._position_window()

        bridge.moveWindowX.connect(self._move_window_x)
        bridge.commitWindowX.connect(self._commit_window_x)
        bridge.maskHeightChanged.connect(self._apply_mask)

        # Defer win32 setup until Qt has processed the window creation event.
        # Use 0ms first; if winId() is not yet available, retry once at 200ms.
        QTimer.singleShot(0, self._setup_win32)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _position_window(self) -> None:
        ax, ay, aw, ah = _primary_ag()
        x = self._saved_x if self._saved_x is not None else ax + (aw - self._bar_w) // 2
        x = max(ax, min(x, ax + aw - self._bar_w))
        self._win.setX(x)
        self._win.setY(ay)
        self._win.setWidth(self._bar_w)
        self._win.setHeight(ah)

    def _setup_win32(self, attempt: int = 0) -> None:
        hwnd = int(self._win.winId())
        if not hwnd:
            if attempt < 5:
                QTimer.singleShot(200, lambda: self._setup_win32(attempt + 1))
            else:
                # Window never became ready; fire on_ready anyway so app isn't stuck
                if self._on_ready:
                    self._on_ready()
                    self._on_ready = None
            return
        self._own_hwnd = hwnd
        setup_toolwindow(self._own_hwnd)
        self._apply_mask(self._pending_visible_h or self._bar_h)
        if self._on_ready:
            self._on_ready()
            self._on_ready = None

    def _apply_mask(self, visible_h: int) -> None:
        self._pending_visible_h = visible_h
        if not self._own_hwnd:
            return
        set_bottom_bar_mask(
            hwnd=self._own_hwnd,
            window_h_logical=int(self._win.height()),
            visible_h_logical=visible_h,
            window_w_logical=self._bar_w,
        )

    def reposition(self) -> None:
        """Call when primary screen changes."""
        self._position_window()
        if self._own_hwnd:
            self._apply_mask(self._pending_visible_h or self._bar_h)

    # ── Drag ─────────────────────────────────────────────────────────────────

    def _move_window_x(self, x: int) -> None:
        ax, _ay, aw, _ah = _primary_ag()
        clamped = max(ax, min(x, ax + aw - self._bar_w))
        self._win.setX(clamped)

    def _commit_window_x(self, x: int) -> None:
        ax, _ay, aw, _ah = _primary_ag()
        clamped = max(ax, min(x, ax + aw - self._bar_w))
        self._bridge.commit_bar_x(clamped)

