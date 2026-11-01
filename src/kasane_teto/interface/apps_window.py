"""Aplicaciones añadidas a mano, para las que no aparecen en el menú Inicio."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from kasane_teto.core.events import EventBus
from kasane_teto.tools.registry import ActionRejected, validate_program


class AppsWindow(QDialog):
    def __init__(self, bus: EventBus, apps: dict[str, str], parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._apps = dict(apps)
        self.setWindowTitle("Aplicaciones permitidas")
        self.resize(460, 320)

        self._list = QListWidget()
        add = QPushButton("Añadir…")
        remove = QPushButton("Quitar")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)

        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Teto ya encuentra las apps del menú Inicio. Añade aquí solo las que no salgan.")
        )
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for name, path in sorted(self._apps.items()):
            self._list.addItem(f"{name} — {path}")

    def _save(self) -> None:
        self._bus.allowed_apps_requested.emit(dict(self._apps))
        self._refresh()

    def _add(self) -> None:
        file, _ = QFileDialog.getOpenFileName(self, "Elegir programa", "", "Programas (*.exe)")
        if not file:
            return
        path = Path(file)
        try:
            validate_program(path)
        except ActionRejected as exc:
            QMessageBox.warning(self, "Aplicaciones", str(exc))
            return
        name, accepted = QInputDialog.getText(
            self, "Nombre", "¿Cómo la llamarás al hablar con Teto?", text=path.stem.casefold()
        )
        if accepted and name.strip():
            self._apps[name.strip().casefold()] = str(path)
            self._save()

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            del self._apps[sorted(self._apps)[row]]
            self._save()
