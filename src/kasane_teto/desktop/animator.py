"""Animación por sprites: elige el fotograma de cada estado con un temporizador."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap

from kasane_teto.character.pack import CharacterPack, PackError
from kasane_teto.character.states import PetState


class SpriteAnimator(QObject):
    frame_changed = Signal()

    def __init__(self, pack: CharacterPack, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._advance)
        self._state = PetState.IDLE
        self._index = 0
        self._running = False
        self._frames: dict[PetState, list[QPixmap]] = {}
        self._pack = pack
        self.set_pack(pack)

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def frame_index(self) -> int:
        return self._index

    def set_pack(self, pack: CharacterPack) -> None:
        self._frames = {
            state: [self._load(path) for path in animation.frames]
            for state, animation in pack.animations.items()
        }
        self._pack = pack
        self._restart()

    def set_state(self, state: PetState) -> None:
        if state is self._state:
            return
        self._state = state
        self._restart()

    def start(self) -> None:
        self._running = True
        self._restart()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()

    def current_pixmap(self) -> QPixmap:
        frames = self._frames.get(self._state, self._frames[PetState.IDLE])
        return frames[self._index]

    @staticmethod
    def _load(path) -> QPixmap:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise PackError(f"Imagen ilegible: {path.name}")
        return pixmap

    def _restart(self) -> None:
        self._index = 0
        self._timer.stop()
        animation = self._pack.animation(self._state)
        if self._running and len(animation.frames) > 1:
            self._timer.start(round(1000 / animation.fps))
        self.frame_changed.emit()

    def _advance(self) -> None:
        count = len(self._pack.animation(self._state).frames)
        self._index = (self._index + 1) % count
        self.frame_changed.emit()
