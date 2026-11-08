"""Mascota Live2D: dibuja el modelo fuera de pantalla con OpenGL y entrega cada fotograma como
imagen a la ventana de la mascota, igual que el animador de sprites.

El modelo se lee desde donde lo tenga el usuario y nunca se copia al proyecto: sus condiciones
prohíben copiarlo o redistribuirlo. Solo se guardan texturas reducidas en la carpeta de datos local,
para gastar una cuarta parte de memoria gráfica.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QOffscreenSurface, QOpenGLContext, QPixmap, QSurfaceFormat

from kasane_teto.character.states import PetState

TEXTURE_SIDE = 2048
MASK_BUFFERS = 3  # el modelo de Teto usa 39 máscaras: con una sola se ven mal
BASE_HEIGHT = 560  # alto de la mascota al 100 %
DEFAULT_RATIO = 1 / 2.318  # ancho entre alto del lienzo de Teto, hasta leer el del modelo
NORMAL_FPS = 30
SLOW_FPS = 12
WATERMARK_EXPRESSION = "Remove Water Mark"
MOUTH_PARAM = "ParamMouthOpenY"
MOUTH_SYLLABLES_PER_SECOND = 5.0
# Expresiones del modelo por estado; los que no aparecen usan la cara normal.
STATE_EXPRESSIONS = {
    PetState.HAPPY: ("Blush",),
    PetState.SURPRISED: ("Star Eye",),
    PetState.CONFUSED: ("Dizzy",),
    PetState.ANGRY: ("Dark Face",),
    PetState.BORED: ("Exp eye",),
}

log = logging.getLogger(__name__)


class Live2DError(Exception):
    """No se pudo cargar o dibujar el modelo."""


def reduced_textures(model_json: Path, cache_root: Path, side: int = TEXTURE_SIDE) -> list[str]:
    """Texturas a `side` px en la caché local; se rehacen si cambia el modelo.

    Se reduce tomando un píxel de cada dos: el modelo guarda color en zonas invisibles, y
    mezclarlo con un filtro dibuja halos alrededor de ojos y boca.
    """
    from PIL import Image

    data = json.loads(model_json.read_text(encoding="utf-8"))
    sources = [model_json.parent / rel for rel in data["FileReferences"]["Textures"]]
    stamp = "|".join(f"{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in sources)
    folder = cache_root / hashlib.sha256(f"{stamp}|{side}".encode()).hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, source in enumerate(sources):
        target = folder / f"texture_{index:02d}.png"
        if not target.exists():
            with Image.open(source) as image:
                if max(image.size) > side:
                    scale = side / max(image.size)
                    size = (round(image.width * scale), round(image.height * scale))
                    image = image.resize(size, Image.Resampling.NEAREST)
                image.save(target)
        paths.append(str(target))
    return paths


def mouth_opening(seconds: float, rng: random.Random) -> float:
    """Boca al hablar: no sigue cada sílaba, pero abre y cierra a ritmo de habla."""
    wave = abs(math.sin(seconds * math.pi * MOUTH_SYLLABLES_PER_SECOND))
    return min(1.0, 0.15 + 0.85 * wave * (0.6 + 0.4 * rng.random()))


class Live2DAnimator(QObject):
    frame_changed = Signal()
    base_changed = Signal()
    failed = Signal(str)

    def __init__(
        self,
        model_json: Path,
        cache_root: Path,
        parent: QObject | None = None,
        cursor: Callable[[], QPointF | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._model_json = model_json
        self._cache_root = cache_root
        self._cursor = cursor
        self._state = PetState.IDLE
        self._talking = False
        self._still = False
        self._slow = False
        self._running = False
        self._rng = random.Random()
        self._last_tick = time.monotonic()
        self._render_size = QSize()
        self._context: QOpenGLContext | None = None
        self._surface: QOffscreenSurface | None = None
        self._fbo = None
        self._model = None
        self._live2d = None
        self._gl = None
        self._base = QSize(round(BASE_HEIGHT * DEFAULT_RATIO), BASE_HEIGHT)
        self._pixmap = self._blank(self._base)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # Interfaz común con SpriteAnimator.

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def base_size(self) -> QSize:
        return QSize(self._base)

    def current_pixmap(self) -> QPixmap:
        return self._pixmap

    def set_render_size(self, size: QSize) -> None:
        """Se dibuja ya al tamaño de la ventana: escalar cada fotograma gastaría CPU."""
        if size == self._render_size or size.isEmpty():
            return
        self._render_size = QSize(size)
        if self._model is not None:
            self._make_framebuffer()

    def set_state(self, state: PetState) -> None:
        if state is self._state:
            return
        self._state = state
        if self._model is not None:
            self._apply_expressions()

    def set_talking(self, talking: bool) -> None:
        self._talking = talking

    def start(self) -> None:
        self._running = True
        self._restart()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()

    def set_pace(self, still: bool = False, max_fps: float | None = None) -> None:
        """Quieta (modo juego o suspendida) suelta el modelo para liberar la memoria gráfica."""
        self._still = still
        self._slow = max_fps is not None
        if still:
            self.release()
        self._restart()

    def release(self) -> None:
        """Deja la última imagen fija y libera texturas y contexto de OpenGL."""
        self._timer.stop()
        if self._context is None:
            return
        self._context.makeCurrent(self._surface)
        self._model = None
        self._fbo = None
        if self._live2d is not None:
            self._live2d.glRelease()
        self._context.doneCurrent()
        self._context = None
        self._surface = None
        log.info("Live2D liberado")

    def shutdown(self) -> None:
        self.release()
        if self._live2d is not None:
            self._live2d.dispose()
            self._live2d = None

    # Carga y dibujo.

    @staticmethod
    def _blank(size: QSize) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap

    def _restart(self) -> None:
        self._timer.stop()
        if not self._running or self._still:
            return
        if self._model is None and not self._load():
            return
        self._last_tick = time.monotonic()
        self._timer.start(round(1000 / (SLOW_FPS if self._slow else NORMAL_FPS)))

    def _load(self) -> bool:
        try:
            self._load_model()
        except Exception as exc:  # una biblioteca nativa puede fallar de muchas formas
            log.exception("No se pudo cargar el modelo Live2D")
            self.release()
            self.failed.emit(str(exc))
            return False
        return True

    def _load_model(self) -> None:
        import live2d
        from OpenGL import GL

        started = time.monotonic()
        textures = reduced_textures(self._model_json, self._cache_root)
        if self._live2d is None:
            live2d.init()
            live2d.enableLog(False)
            self._live2d = live2d
        self._gl = GL
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        self._context = QOpenGLContext()
        self._context.setFormat(fmt)
        if not self._context.create():
            raise Live2DError("No se pudo crear el contexto de OpenGL")
        self._surface = QOffscreenSurface()
        self._surface.setFormat(fmt)
        self._surface.create()
        if not self._context.makeCurrent(self._surface):
            raise Live2DError("No se pudo activar el contexto de OpenGL")
        live2d.glInit()
        data = json.loads(self._model_json.read_text(encoding="utf-8"))
        data["FileReferences"]["Textures"] = textures
        model = live2d.Model()
        model.LoadFromJsonString(json.dumps(data, ensure_ascii=False), False, str(self._model_json.parent))
        model.CreateRenderer(MASK_BUFFERS)
        home = self._model_json.parent
        for path in sorted((home / "Expressions").glob("*.exp3.json")):
            model.LoadExtraExpression(path.name.removesuffix(".exp3.json"), str(path))
        for path in sorted((home / "Motions").glob("*.motion3.json")):
            model.LoadExtraMotion(path.name.removesuffix(".motion3.json"), str(path))
        width, height = model.GetCanvasSize()
        base = QSize(round(BASE_HEIGHT * width / height), BASE_HEIGHT) if width and height else self._base
        self._model = model
        if base != self._base:
            self._base = base
            self.base_changed.emit()
        self._apply_expressions()
        if self._render_size.isEmpty():
            self._render_size = QSize(self._base)
        self._make_framebuffer()
        log.info("Live2D cargado en %.1f s", time.monotonic() - started)

    def _make_framebuffer(self) -> None:
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

        assert self._context is not None and self._model is not None
        self._context.makeCurrent(self._surface)
        fbo_format = QOpenGLFramebufferObjectFormat()
        fbo_format.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
        self._fbo = QOpenGLFramebufferObject(self._render_size, fbo_format)
        self._model.Resize(self._render_size.width(), self._render_size.height())

    def _apply_expressions(self) -> None:
        """La marca de agua la quita una expresión del propio modelo, pensada para eso."""
        assert self._model is not None
        self._model.ResetExpressions()
        for name in (WATERMARK_EXPRESSION, *STATE_EXPRESSIONS.get(self._state, ())):
            self._model.AddExpression(name)

    def _tick(self) -> None:
        if self._model is None or self._context is None or self._fbo is None:
            return
        now = time.monotonic()
        delta, self._last_tick = now - self._last_tick, now
        try:
            self._context.makeCurrent(self._surface)
            self._follow_cursor()
            self._model.Update(delta)
            talking = self._talking or self._state is PetState.SPEAKING
            self._model.SetParamById(MOUTH_PARAM, mouth_opening(now, self._rng) if talking else 0.0)
            self._fbo.bind()
            self._gl.glViewport(0, 0, self._render_size.width(), self._render_size.height())
            self._live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
            self._model.Draw()
            image = self._fbo.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            self._fbo.release()
        except Exception as exc:
            log.exception("Fallo al dibujar Live2D")
            self.release()
            self.failed.emit(str(exc))
            return
        self._pixmap = QPixmap.fromImage(image)
        self.frame_changed.emit()

    def _follow_cursor(self) -> None:
        """Mira hacia el ratón leyendo su posición, como cualquier ventana: sin ganchos."""
        if self._cursor is None:
            return
        point = self._cursor()
        if point is not None:
            self._model.Drag(point.x(), point.y())
