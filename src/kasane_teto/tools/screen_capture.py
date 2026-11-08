"""Captura la pantalla solo cuando el usuario lo pide. La imagen vive en memoria, nunca en disco."""

from __future__ import annotations

import base64
import ctypes
from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QCursor, QGuiApplication

MAX_IMAGE_SIDE = 1024
JPEG_QUALITY = 80
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004 o posterior

_user32 = ctypes.WinDLL("user32", use_last_error=True)


class CaptureError(Exception):
    """No se pudo capturar la pantalla."""


@contextmanager
def _without_own_windows() -> Iterator[None]:
    """La mascota y el chat de Teto no salen en la captura: si no, se describe a sí misma.

    Solo dura la captura, para que el usuario pueda seguir grabando o retransmitiendo a Teto.
    """
    handles = [int(w.winId()) for w in QGuiApplication.topLevelWindows() if w.isVisible()]
    for handle in handles:
        _user32.SetWindowDisplayAffinity(handle, WDA_EXCLUDEFROMCAPTURE)
    try:
        yield
    finally:
        for handle in handles:
            _user32.SetWindowDisplayAffinity(handle, WDA_NONE)


def capture_screen_url() -> str:
    """Debe llamarse desde el hilo de la interfaz. Se captura la pantalla donde está el ratón."""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        raise CaptureError("No hay pantalla")
    with _without_own_windows():
        image = screen.grabWindow(0)
    if image.isNull():
        raise CaptureError("La captura salió vacía")
    scaled = image.scaled(
        MAX_IMAGE_SIDE,
        MAX_IMAGE_SIDE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not scaled.save(buffer, "JPEG", JPEG_QUALITY):
        raise CaptureError("No se pudo comprimir la captura")
    return "data:image/jpeg;base64," + base64.b64encode(bytes(buffer.data())).decode("ascii")
