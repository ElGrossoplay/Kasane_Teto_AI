"""Animación por sprites: elige el fotograma de cada estado con un temporizador."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap

from kasane_teto.character.pack import CharacterPack, PackError
from kasane_teto.character.states import PetState


class SpriteAnimator(QObject):
    frame_changed = Signal()
    base_changed = Signal()

    def __init__(self, pack: CharacterPack, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._advance)
        self._state = PetState.IDLE
        self._index = 0
        self._running = False
        self._still = False
        self._max_fps: float | None = None
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
        self.base_changed.emit()

    def base_size(self) -> QSize:
        return self.current_pixmap().size()

    def set_render_size(self, size: QSize) -> None:
        """Los sprites los escala la ventana; Live2D dibuja ya al tamaño pedido."""

    def set_talking(self, talking: bool) -> None:
        """Los sprites tienen su propio estado de hablar."""

    def play_gesture(self, name: str) -> None:
        """Los gestos de cuerpo son cosa de Live2D; los sprites solo cambian de imagen."""

    def poke(self) -> None:
        """Sin reacción al clic."""

    def set_looks(self, names: list[str]) -> None:
        """Las variantes de aspecto son del modelo Live2D."""

    def set_low_performance(self, low: bool) -> None:
        """Los sprites ya gastan muy poco."""

    def note_drag(self, pixels: float) -> None:
        """Sin inercia al arrastrar."""

    def shutdown(self) -> None:
        self.stop()

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

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def set_pace(self, still: bool = False, max_fps: float | None = None) -> None:
        """Quieta en modo juego o suspendida; con menos fotogramas cuando nadie la usa."""
        if (still, max_fps) == (self._still, self._max_fps):
            return
        self._still = still
        self._max_fps = max_fps
        self._restart()

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
        if self._running and not self._still and len(animation.frames) > 1:
            fps = min(animation.fps, self._max_fps or animation.fps)
            self._timer.start(round(1000 / fps))
        self.frame_changed.emit()

    def _advance(self) -> None:
        count = len(self._pack.animation(self._state).frames)
        self._index = (self._index + 1) % count
        self.frame_changed.emit()
