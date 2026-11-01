"""Ventanas de Windows: lee títulos y pide cerrar, minimizar o restaurar, como los botones.

No abre ningún proceso. Tampoco toca juegos, que la regla de anticheat prohíbe: se omiten las
ventanas a pantalla completa, sin barra de título o con clase o título de juego.
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
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
MAX_CLASS_CHARS = 128
# Clases de ventana de los motores de juegos, para los que se juegan en ventana.
GAME_CLASSES = frozenset(
    "UnrealWindow UnityWndClass RiotWindowClass RCLIENT Valve001 SDL_app GLFW30 "
    "CryENGINE id_app_window".split()
)
# Navegadores, Discord y similares: una pestaña sobre un juego no es el juego.
WEB_CLASSES = frozenset(("Chrome_WidgetWin_1", "MozillaWindowClass"))
GAME_TITLES = (
    "valorant", "league of legends", "riot client", "fortnite", "counter-strike", "apex legends",
    "overwatch", "minecraft", "genshin impact", "roblox",
)

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
_user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)


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


def is_game_window(kind: str, title: str) -> bool:
    """El título debe empezar por el juego: Discord pone el canal "Minecraft" en el suyo."""
    if kind in GAME_CLASSES:
        return True
    return kind not in WEB_CLASSES and title.casefold().startswith(GAME_TITLES)


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(MAX_CLASS_CHARS)
    _user32.GetClassNameW(hwnd, buffer, MAX_CLASS_CHARS)
    return buffer.value


def list_windows() -> list[Window]:
    """Ventanas normales del escritorio; lo que no parezca una, por prudencia, no se incluye."""
    found: list[Window] = []

    def visit(hwnd: int, _extra: int) -> bool:
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, GW_OWNER):
            return True
        if not _user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CAPTION:
            return True
        title = _title(hwnd)
        if not title or is_game_window(_class_name(hwnd), title):
            return True
        # Maximizada, Windows la hace algo mayor que la pantalla: no es pantalla completa.
        if _user32.IsIconic(hwnd) or _user32.IsZoomed(hwnd) or not _is_fullscreen(hwnd):
            found.append(Window(hwnd, title))
        return True

    _user32.EnumWindows(_EnumProc(visit), 0)
    return found


def foreground_window() -> int:
    return int(_user32.GetForegroundWindow() or 0)


@dataclass(frozen=True)
class Foreground:
    title: str
    is_game: bool


def foreground() -> Foreground:
    """Solo lee el título. Lo que ocupe toda la pantalla sin ser web se trata como juego."""
    hwnd = foreground_window()
    if not hwnd:
        return Foreground("", False)
    title, kind = _title(hwnd), _class_name(hwnd)
    fullscreen = not _user32.IsZoomed(hwnd) and _is_fullscreen(hwnd)
    return Foreground(title, is_game_window(kind, title) or (fullscreen and kind not in WEB_CLASSES))


def game_on_screen() -> bool:
    """Hay un juego delante o abierto en cualquier monitor: entonces no se captura nada."""
    if foreground().is_game:
        return True
    found: list[bool] = []

    def visit(hwnd: int, _extra: int) -> bool:
        if _user32.IsWindowVisible(hwnd) and is_game_window(_class_name(hwnd), _title(hwnd)):
            found.append(True)
            return False
        return True

    _user32.EnumWindows(_EnumProc(visit), 0)
    return bool(found)


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def seconds_since_input() -> float:
    """Tiempo sin tocar teclado ni ratón, sin ganchos: lo da el propio Windows."""
    info = _LastInput(cbSize=ctypes.sizeof(_LastInput))
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now = ctypes.windll.kernel32.GetTickCount()
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def close_window(handle: int) -> None:
    """Si hay algo sin guardar, es la propia aplicación la que pregunta."""
    if not _user32.PostMessageW(handle, WM_CLOSE, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def show_window(handle: int, mode: int) -> None:
    """Asíncrono: una aplicación colgada no debe bloquear a Teto."""
    if not _user32.ShowWindowAsync(handle, mode):
        ctypes.set_last_error(0)

