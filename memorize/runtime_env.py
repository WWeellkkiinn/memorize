from __future__ import annotations

import os
import sys


def _set_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
        try:
            shcore = ctypes.windll.shcore
            if shcore.SetProcessDpiAwareness(2) == 0:
                return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _sanitize_path() -> None:
    raw = os.environ.get("PATH", "")
    if not raw:
        return
    blocked_tokens = (
        "\\anaconda3\\library\\bin",
        "\\anaconda3\\dlls",
        "\\anaconda3\\libs",
        "\\anaconda3\\envs\\",
    )
    kept: list[str] = []
    for item in raw.split(os.pathsep):
        part = item.strip()
        if not part:
            continue
        if not any(t in part.lower() for t in blocked_tokens):
            kept.append(part)
    os.environ["PATH"] = os.pathsep.join(kept)


def prepare_runtime_env() -> None:
    _set_windows_dpi_awareness()
    if getattr(sys, "frozen", False):
        for key in ("PYTHONHOME", "PYTHONPATH"):
            os.environ.pop(key, None)
        _sanitize_path()
