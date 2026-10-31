"""Icono y menú de la bandeja del sistema."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from kasane_teto.character.states import STATE_LABELS
from kasane_teto.core.events import EventBus


class TrayIcon(QObject):
    def __init__(
        self, icon: QIcon, always_on_top: bool, bus: EventBus, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._menu = QMenu()

        self._menu.addAction("Mostrar u ocultar").triggered.connect(
            lambda: bus.pet_visibility_toggled.emit()
        )
        self._always_on_top = QAction("Siempre encima", self._menu, checkable=True)
        self._always_on_top.setChecked(always_on_top)
        self._always_on_top.toggled.connect(bus.always_on_top_requested)
        self._menu.addAction(self._always_on_top)

        # Solo para probar la animación hasta que la IA cambie los estados (Fase 2).
        states_menu = self._menu.addMenu("Probar estado")
        for state, label in STATE_LABELS.items():
            states_menu.addAction(label).triggered.connect(
                lambda _checked=False, s=state: bus.pet_state_requested.emit(s)
            )

        self._menu.addSeparator()
        self._menu.addAction("Configuración…").triggered.connect(
            lambda: bus.settings_requested.emit()
        )
        self._menu.addAction("Salir").triggered.connect(lambda: bus.quit_requested.emit())

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Kasane Teto AI")
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

        bus.always_on_top_changed.connect(self._always_on_top.setChecked)
        bus.context_menu_requested.connect(self._show_menu)

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def _show_menu(self, position: QPoint) -> None:
        self._menu.popup(position)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.Trigger:
            self._bus.pet_visibility_toggled.emit()
