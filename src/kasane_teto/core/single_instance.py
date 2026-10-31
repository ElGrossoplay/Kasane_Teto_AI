"""Garantiza una sola instancia; la segunda avisa a la primera y termina."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_TIMEOUT_MS = 500


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, data_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = QLockFile(str(data_dir / "app.lock"))
        self._lock.setStaleLockTime(0)
        digest = hashlib.sha256(str(data_dir).encode("utf-8")).hexdigest()[:16]
        self._server_name = f"KasaneTetoAI-{digest}"
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        if not self._lock.tryLock(0):
            self._notify_running_instance()
            return False
        QLocalServer.removeServer(self._server_name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(self._server_name)
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()

    def _notify_running_instance(self) -> None:
        socket = QLocalSocket(self)
        socket.connectToServer(self._server_name)
        socket.waitForConnected(CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        socket.deleteLater()

    def _on_connection(self) -> None:
        assert self._server is not None
        connection = self._server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
            connection.deleteLater()
        self.activated.emit()
