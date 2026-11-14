"""Atajo global con RegisterHotKey: sin ganchos de teclado, seguro frente a anticheat."""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


@dataclass(frozen=True)
class Shortcut:
    """Atajo Ctrl+Alt+letra. Cada uno necesita un identificador propio."""

    hotkey_id: int
    key: str

    @property
    def label(self) -> str:
        return f"Ctrl+Alt+{self.key}"


TALK = Shortcut(0x7E70, "T")
CHAT = Shortcut(0x7E71, "C")
SHOW = Shortcut(0x7E72, "H")
HOTKEY_LABEL = TALK.label

log = logging.getLogger(__name__)


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None], hotkey_id: int) -> None:
        super().__init__()
        self._callback = callback
        self._id = hotkey_id

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._id:
                self._callback()
                return True, 0
        return False, 0


class GlobalHotkey:
    def __init__(self, callback: Callable[[], None], shortcut: Shortcut = TALK) -> None:
        self._shortcut = shortcut
        self._filter = _Filter(callback, shortcut.hotkey_id)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self) -> bool:
        if self._registered:
            return True
        modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        shortcut = self._shortcut
        if not self._user32.RegisterHotKey(None, shortcut.hotkey_id, modifiers, ord(shortcut.key)):
            log.warning("Atajo %s no disponible: lo usa otro programa", shortcut.label)
            return False
        QCoreApplication.instance().installNativeEventFilter(self._filter)
        self._registered = True
        return True

    def unregister(self) -> None:
        if self._registered:
            self._user32.UnregisterHotKey(None, self._shortcut.hotkey_id)
            QCoreApplication.instance().removeNativeEventFilter(self._filter)
            self._registered = False
