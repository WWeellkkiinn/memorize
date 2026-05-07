"""Win32 helpers for Memorize bottom bar."""
from __future__ import annotations
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
DwmSetWindowAttribute = ctypes.windll.dwmapi.DwmSetWindowAttribute

_IS_64 = ctypes.sizeof(ctypes.c_void_p) == 8
if _IS_64:
    GetWindowLongPtr = user32.GetWindowLongPtrW
    SetWindowLongPtr = user32.SetWindowLongPtrW
else:
    GetWindowLongPtr = user32.GetWindowLongW
    SetWindowLongPtr = user32.SetWindowLongW

GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongPtr.restype = ctypes.c_ssize_t
SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
SetWindowLongPtr.restype = ctypes.c_ssize_t

ctypes.windll.dwmapi.DwmSetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
]
ctypes.windll.dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateRectRgn.restype = wintypes.HANDLE
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT


GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    ctypes.c_ssize_t,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL


def set_bottom_bar_mask(
    hwnd: int,
    window_h_logical: int,
    visible_h_logical: int,
    window_w_logical: int,
) -> None:
    """Clip window to expose only visible_h_logical pixels at the bottom edge."""
    try:
        dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd))
        scale = dpi / 96.0 if dpi else 1.0
        win_h = round(window_h_logical * scale)
        vis_h = round(visible_h_logical * scale)
        win_w = round(window_w_logical * scale)
        hrgn = gdi32.CreateRectRgn(0, win_h - vis_h, win_w, win_h)
        user32.SetWindowRgn(wintypes.HWND(hwnd), hrgn, wintypes.BOOL(True))
        # SetWindowRgn takes ownership of hrgn — do NOT DeleteObject
    except Exception:
        pass


def setup_toolwindow(hwnd: int) -> None:
    """Remove taskbar entry, restore TOPMOST after style change, remove DWM border."""
    h = wintypes.HWND(hwnd)
    try:
        ex = GetWindowLongPtr(h, GWL_EXSTYLE)
        SetWindowLongPtr(h, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        user32.SetWindowPos(
            h, HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        pass
    try:
        color = ctypes.c_uint(DWMWA_COLOR_NONE)
        DwmSetWindowAttribute(h, DWMWA_BORDER_COLOR, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass
