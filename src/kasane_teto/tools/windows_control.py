"""Ventanas de Windows: solo lee títulos y pide cerrar, como pulsar la X.

No abre ningún proceso. Tampoco toca ventanas a pantalla completa o sin barra de título, que es
como se presentan los juegos: la regla de anticheat prohíbe interactuar con ellos.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

GW_OWNER = 4
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WM_CLOSE = 0x0010
MONITOR_DEFAULTTONEAREST = 2

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = (_EnumProc, wintypes.LPARAM)
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongPtrW.restype = ctypes.c_longlong
_user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo))


@dataclass(frozen=True)
class Window:
    handle: int
    title: str


def _title(hwnd: int) -> str:
    size = _user32.GetWindowTextLengthW(hwnd)
    if not size:
        return ""
    buffer = ctypes.create_unicode_buffer(size + 1)
    _user32.GetWindowTextW(hwnd, buffer, size + 1)
    return buffer.value


def _is_fullscreen(hwnd: int) -> bool:
    window = wintypes.RECT()
    info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
    monitor = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not _user32.GetWindowRect(hwnd, ctypes.byref(window)) or not monitor:
        return True
    if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return True
    screen = info.rcMonitor
    return (
        window.left <= screen.left
        and window.top <= screen.top
        and window.right >= screen.right
        and window.bottom >= screen.bottom
    )


def list_windows() -> list[Window]:
    """Ventanas normales del escritorio; lo que no parezca una, por prudencia, no se incluye."""
    found: list[Window] = []

    def visit(hwnd: int, _extra: int) -> bool:
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, GW_OWNER):
            return True
        if not _user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CAPTION:
            return True
        title = _title(hwnd)
        if title and not _is_fullscreen(hwnd):
            found.append(Window(hwnd, title))
        return True

    _user32.EnumWindows(_EnumProc(visit), 0)
    return found


def close_window(handle: int) -> None:
    """Si hay algo sin guardar, es la propia aplicación la que pregunta."""
    if not _user32.PostMessageW(handle, WM_CLOSE, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())
