"""Estados de actividad: activa, inactiva, suspendida y modo juego.

Para saber si hay un juego solo lee el título y la clase de la ventana en primer plano, como el
resto de la app: no abre ni lista procesos, que la regla de anticheat prohíbe.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

from kasane_teto.core.events import EventBus
from kasane_teto.core.settings import Settings
from kasane_teto.tools.windows_control import Foreground, foreground, game_on_screen

# Dos lecturas seguidas: un juego que se abre un momento no debe cambiar nada.
GAME_CHECKS_TO_ENTER = 2

log = logging.getLogger(__name__)


class Activity(Enum):
    ACTIVE = "activa"
    IDLE = "inactiva"
    SUSPENDED = "suspendida"
    GAME = "modo juego"


class ActivityService(QObject):
    changed = Signal(object)

    def __init__(
        self,
        bus: EventBus,
        settings: Settings,
        parent: QObject | None = None,
        read_foreground: Callable[[], Foreground] = foreground,
        game_open: Callable[[], bool] = game_on_screen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._settings = settings
        self._read_foreground = read_foreground
        self._game_open = game_open
        self._clock = clock
        self._last_use = clock()
        self._last_game_seen = 0.0
        self._game_checks = 0
        self._manual_game = False
        self._auto_game = False
        self._auto_blocked = False
        self._suspended = False
        self._state = Activity.ACTIVE

        for signal in (bus.user_message, bus.assistant_done, bus.listen_started, bus.chat_requested):
            signal.connect(self._mark_use)
        bus.game_mode_requested.connect(self.set_manual_game)
        bus.suspend_requested.connect(self.set_suspended)
        bus.game_mode_auto_requested.connect(self._set_auto_enabled)

        self._timer = QTimer(self)
        self._timer.setInterval(int(float(settings.get("game_mode.check_seconds", 5)) * 1000))
        self._timer.timeout.connect(self.check)
        self._timer.start()

    @property
    def state(self) -> Activity:
        return self._state

    @property
    def auto_enabled(self) -> bool:
        return bool(self._settings.get("game_mode.auto", True))

    def _set_auto_enabled(self, enabled: bool) -> None:
        self._settings.set("game_mode.auto", enabled)
        if not enabled:
            self._auto_game = False
            self._game_checks = 0
        self._update()

    def set_manual_game(self, enabled: bool) -> None:
        self._manual_game = enabled
        if not enabled and self._auto_game:
            # Quitarlo a mano con el juego delante lo respeta hasta que el juego deje de verse.
            self._auto_game = False
            self._auto_blocked = True
        self._update()

    def set_suspended(self, suspended: bool) -> None:
        self._suspended = suspended
        self._last_use = self._clock()
        self._update()

    def _mark_use(self, *_args: object) -> None:
        self._last_use = self._clock()
        if self._suspended:
            log.info("Uso de la app: Teto deja de estar suspendida")
            self._suspended = False
        self._update()

    def _is_game(self, current: Foreground) -> bool:
        if not current.title:
            return False
        extra = tuple(t.casefold() for t in self._settings.get("game_mode.titles", []) if t)
        return current.is_game or bool(extra) and current.title.casefold().startswith(extra)

    def check(self) -> None:
        if self.auto_enabled:
            self._check_game()
        self._update()

    def _check_game(self) -> None:
        now = self._clock()
        if self._is_game(self._read_foreground()):
            self._last_game_seen = now
            self._game_checks += 1
            if self._game_checks >= GAME_CHECKS_TO_ENTER and not self._auto_blocked:
                self._auto_game = True
            return
        self._game_checks = 0
        self._auto_blocked = False
        if not self._auto_game:
            return
        # Al pasar a Discord un momento el juego sigue abierto: se espera antes de salir.
        exit_after = float(self._settings.get("game_mode.exit_seconds", 30))
        if now - self._last_game_seen >= exit_after and not self._game_open():
            self._auto_game = False

    def _update(self) -> None:
        idle_after = float(self._settings.get("pet.idle_minutes", 5)) * 60
        if self._suspended:
            state = Activity.SUSPENDED
        elif self._manual_game or self._auto_game:
            state = Activity.GAME
        elif self._clock() - self._last_use >= idle_after:
            state = Activity.IDLE
        else:
            state = Activity.ACTIVE
        if state is not self._state:
            log.info("Estado de actividad: %s → %s", self._state.value, state.value)
            self._state = state
            self.changed.emit(state)

    def shutdown(self) -> None:
        self._timer.stop()
