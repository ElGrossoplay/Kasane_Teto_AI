"""Comentarios por su cuenta cuando pasa un rato sin hablar. Solo mira el título de la ventana.

Durante un juego usa frases preparadas: cargar la IA quitaría VRAM y fotogramas al juego.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from kasane_teto.core.events import EventBus
from kasane_teto.core.settings import Settings
from kasane_teto.tools.registry import ToolRegistry

CHECK_INTERVAL_MS = 30_000
GAME_NAME_CHARS = 30

log = logging.getLogger(__name__)


def load_game_lines() -> list[str]:
    path = Path(__file__).resolve().parents[1] / "personality" / "prompts" / "comentarios_juego.txt"
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CommentService(QObject):
    def __init__(
        self,
        bus: EventBus,
        settings: Settings,
        tools: ToolRegistry,
        comment: Callable[[str], bool],
        parent: QObject | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._settings = settings
        self._tools = tools
        self._comment = comment
        self._clock = clock
        self._last_activity = clock()
        self._last_title = ""
        self._lines = load_game_lines()

        for signal in (bus.user_message, bus.assistant_done):
            signal.connect(self._mark_activity)
        bus.comments_enabled_requested.connect(self._set_enabled)
        bus.comments_minutes_requested.connect(self._set_minutes)

        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.check)
        if self.enabled:
            self._timer.start()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("comments.enabled", False))

    def _mark_activity(self, *_args: object) -> None:
        self._last_activity = self._clock()

    def _set_enabled(self, enabled: bool) -> None:
        self._settings.set("comments.enabled", enabled)
        self._mark_activity()
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def _set_minutes(self, minutes: int) -> None:
        self._settings.set("comments.minutes", minutes)

    def _is_due(self) -> bool:
        wait = float(self._settings.get("comments.minutes", 10)) * 60
        away = float(self._settings.get("comments.away_minutes", 5)) * 60
        if self._clock() - self._last_activity < wait:
            return False
        return self._tools.seconds_since_input() < away

    def check(self) -> None:
        """Se comenta una vez por ventana: repetir lo mismo cada rato cansa."""
        if not self.enabled or not self._is_due():
            return
        current = self._tools.foreground()
        if not current.title or current.title == self._last_title:
            return
        if current.is_game:
            self._say_game_line(current.title)
        elif not self._comment(current.title):
            return
        self._last_title = current.title
        self._mark_activity()

    def _say_game_line(self, title: str) -> None:
        line = random.choice(self._lines).format(juego=title[:GAME_NAME_CHARS].strip())
        self._bus.assistant_token.emit(line)
        self._bus.assistant_done.emit()

    def shutdown(self) -> None:
        self._timer.stop()
