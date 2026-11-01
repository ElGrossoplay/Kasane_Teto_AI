"""Atajo global con RegisterHotKey: sin ganchos de teclado, seguro frente a anticheat."""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

HOTKEY_ID = 0x7E70
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_T = 0x54
WM_HOTKEY = 0x0312
HOTKEY_LABEL = "Ctrl+Alt+T"

log = logging.getLogger(__name__)


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._callback()
                return True, 0
        return False, 0


class GlobalHotkey:
    def __init__(self, callback: Callable[[], None]) -> None:
        self._filter = _Filter(callback)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self) -> bool:
        if self._registered:
            return True
        modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        if not self._user32.RegisterHotKey(None, HOTKEY_ID, modifiers, VK_T):
            log.warning("Atajo %s no disponible: lo usa otro programa", HOTKEY_LABEL)
            return False
        QCoreApplication.instance().installNativeEventFilter(self._filter)
        self._registered = True
        return True

    def unregister(self) -> None:
        if self._registered:
            self._user32.UnregisterHotKey(None, HOTKEY_ID)
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._registered = False
