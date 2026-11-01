"""Captura la pantalla solo cuando el usuario lo pide. La imagen vive en memoria, nunca en disco."""

from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QCursor, QGuiApplication

MAX_IMAGE_SIDE = 1024
JPEG_QUALITY = 80


class CaptureError(Exception):
    """No se pudo capturar la pantalla."""


def capture_screen_url() -> str:
    """Debe llamarse desde el hilo de la interfaz. Se captura la pantalla donde está el ratón."""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        raise CaptureError("No hay pantalla")
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
