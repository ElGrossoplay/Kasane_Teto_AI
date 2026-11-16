"""Icono y menú de la bandeja del sistema."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from kasane_teto.character.states import STATE_LABELS
from kasane_teto.core.events import EventBus
from kasane_teto.desktop.hotkey import CHAT, SHOW, TALK

SCALES = (50, 75, 100, 125, 150, 200)
# Nombres en español de las variantes del modelo de Teto; las de otro modelo salen con su nombre.
LOOK_LABELS = {
    "chibi": "Chibi",
    "SV Utau ALT": "Traje alternativo (SV/UTAU)",
    "【SV】Mic": "Con micrófono",
    "【SV】Baguette": "Con baguette",
    "【Utau】Mic": "Con auriculares",
}
GESTURE_LABELS = {
    "wave": "Saludar",
    "hop": "Dar un saltito",
    "stretch": "Estirarse",
    "look_around": "Mirar alrededor",
    "nod": "Asentir",
    "shake": "Negar",
}


class TrayIcon(QObject):
    def __init__(
        self, icon: QIcon, always_on_top: bool, bus: EventBus, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._menu = QMenu()

        # El texto tras el tabulador se muestra como atajo; los atajos los registra la app.
        chat = self._menu.addAction(f"Hablar con Teto\t{CHAT.label}")
        chat.triggered.connect(lambda: bus.chat_requested.emit())
        font = chat.font()
        font.setBold(True)
        chat.setFont(font)
        self._menu.addAction(f"Escuchar\t{TALK.label}").triggered.connect(
            lambda: bus.listen_toggled.emit()
        )
        self._menu.addAction("Callar").triggered.connect(
            lambda: bus.generation_stop_requested.emit()
        )
        self._menu.addSeparator()
        self._menu.addAction(f"Mostrar u ocultar\t{SHOW.label}").triggered.connect(
            lambda: bus.pet_visibility_toggled.emit()
        )
        self._always_on_top = QAction("Siempre encima", self._menu, checkable=True)
        self._always_on_top.setChecked(always_on_top)
        self._always_on_top.toggled.connect(bus.always_on_top_requested)
        self._menu.addAction(self._always_on_top)
        scale_menu = self._menu.addMenu("Tamaño")
        for scale in SCALES:
            scale_menu.addAction(f"{scale} %").triggered.connect(
                lambda _checked=False, s=scale: bus.scale_requested.emit(s)
            )

        self._looks_menu = self._menu.addMenu("Aspecto")
        self._looks_menu.menuAction().setVisible(False)
        moves_menu = self._menu.addMenu("Gestos y expresiones")
        for gesture, label in GESTURE_LABELS.items():
            moves_menu.addAction(label).triggered.connect(
                lambda _checked=False, g=gesture: bus.gesture_requested.emit(g)
            )
        moves_menu.addSeparator()
        for state, label in STATE_LABELS.items():
            moves_menu.addAction(label).triggered.connect(
                lambda _checked=False, s=state: bus.pet_state_requested.emit(s)
            )

        self._menu.addSeparator()
        self._low = QAction("Bajo rendimiento", self._menu, checkable=True)
        self._low.setToolTip("Anima con la mitad de fotogramas: gasta la mitad de CPU.")
        self._low.toggled.connect(bus.low_performance_requested)
        self._menu.addAction(self._low)
        self._game_mode = QAction("Modo juego", self._menu, checkable=True)
        self._game_mode.setToolTip("Libera la GPU, apaga el oído y deja quieta a Teto.")
        self._game_mode.triggered.connect(bus.game_mode_requested)
        self._menu.addAction(self._game_mode)
        self._suspend = QAction("Suspender", self._menu, checkable=True)
        self._suspend.triggered.connect(bus.suspend_requested)
        self._menu.addAction(self._suspend)
        self._menu.addAction("Liberar memoria de la IA").triggered.connect(
            lambda: bus.ai_unload_requested.emit()
        )
        self._menu.addAction("Memoria…").triggered.connect(
            lambda: bus.memory_panel_requested.emit()
        )
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

    def notify(self, text: str) -> None:
        self._tray.showMessage("Kasane Teto AI", text, QSystemTrayIcon.MessageIcon.Warning)

    def set_low_performance(self, low: bool) -> None:
        self._low.blockSignals(True)
        self._low.setChecked(low)
        self._low.blockSignals(False)

    def set_looks(self, available: list[str], active: list[str]) -> None:
        """Variantes de aspecto del modelo actual; sin modelo Live2D, el menú se esconde."""
        self._looks_menu.clear()
        self._looks_menu.menuAction().setVisible(bool(available))
        for name in available:
            action = self._looks_menu.addAction(LOOK_LABELS.get(name, name))
            action.setCheckable(True)
            action.setChecked(name in active)
            action.toggled.connect(lambda on, n=name: self._bus.look_toggled.emit(n, on))

    def set_activity(self, label: str, game: bool, suspended: bool) -> None:
        """Refleja el estado, también cuando el modo juego se activa solo."""
        self._game_mode.setChecked(game)
        self._suspend.setChecked(suspended)
        self._tray.setToolTip(f"Kasane Teto AI ({label})")

    def _show_menu(self, position: QPoint) -> None:
        self._menu.popup(position)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.Trigger:
            self._bus.pet_visibility_toggled.emit()
