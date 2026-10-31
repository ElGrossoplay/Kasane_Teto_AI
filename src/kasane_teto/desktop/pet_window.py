"""Ventana transparente de la mascota."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import (
    QContextMenuEvent,
    QGuiApplication,
    QHideEvent,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from kasane_teto.core.events import EventBus
from kasane_teto.core.settings import Settings
from kasane_teto.desktop.animator import SpriteAnimator

MIN_SCALE = 25
MAX_SCALE = 300
SCALE_STEP = 10
SAVE_POSITION_DELAY_MS = 500
SCREEN_MARGIN = 24
MAX_CACHED_FRAMES = 8


def clamp_scale(scale: int) -> int:
    return max(MIN_SCALE, min(MAX_SCALE, scale))


class PetWindow(QWidget):
    def __init__(self, animator: SpriteAnimator, settings: Settings, bus: EventBus) -> None:
        super().__init__()
        self._animator = animator
        self._settings = settings
        self._bus = bus
        self._scale = clamp_scale(int(settings.get("pet.scale", 100)))
        self._scaled_target: tuple[QSize, float] | None = None
        self._scaled: dict[int, QPixmap] = {}

        self.setWindowTitle("Kasane Teto AI")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, bool(settings.get("pet.always_on_top", True))
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_POSITION_DELAY_MS)
        self._save_timer.timeout.connect(self.save_position)

        animator.frame_changed.connect(self.update)
        self._apply_size()
        self._restore_position()

    @property
    def scale_percent(self) -> int:
        return self._scale

    @property
    def always_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def set_scale(self, scale: int) -> None:
        scale = clamp_scale(scale)
        if scale == self._scale:
            return
        bottom_center = QPoint(self.geometry().center().x(), self.geometry().bottom())
        self._scale = scale
        self._apply_size()
        self.move(bottom_center.x() - self.width() // 2, bottom_center.y() - self.height() + 1)
        self._keep_on_screen()
        self._settings.set("pet.scale", scale)
        self._bus.scale_changed.emit(scale)

    def set_always_on_top(self, enabled: bool) -> None:
        if enabled == self.always_on_top:
            return
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()
        self._settings.set("pet.always_on_top", enabled)
        self._bus.always_on_top_changed.emit(enabled)

    def refresh_size(self) -> None:
        """Ajusta la ventana tras cambiar de paquete de personaje."""
        self._apply_size()
        self.update()

    def toggle_visibility(self) -> None:
        self.setVisible(not self.isVisible())

    def save_position(self) -> None:
        self._settings.set("pet.x", self.x())
        self._settings.set("pet.y", self.y())

    def _apply_size(self) -> None:
        base = self._animator.current_pixmap().size()
        self.setFixedSize(
            max(1, base.width() * self._scale // 100), max(1, base.height() * self._scale // 100)
        )
        self._scaled.clear()

    def _keep_on_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) or self.screen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    def _restore_position(self) -> None:
        x, y = self._settings.get("pet.x"), self._settings.get("pet.y")
        if isinstance(x, int) and isinstance(y, int):
            center = QRect(x, y, self.width(), self.height()).center()
            if QGuiApplication.screenAt(center) is not None:
                self.move(x, y)
                return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - SCREEN_MARGIN,
            area.bottom() - self.height() - SCREEN_MARGIN,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._scaled_pixmap())

    def _scaled_pixmap(self) -> QPixmap:
        source = self._animator.current_pixmap()
        ratio = self.devicePixelRatioF()
        target = (self.size(), ratio)
        if target != self._scaled_target or len(self._scaled) >= MAX_CACHED_FRAMES:
            self._scaled.clear()
            self._scaled_target = target
        scaled = self._scaled.get(source.cacheKey())
        if scaled is None:
            scaled = source.scaled(
                self.size() * ratio,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(ratio)
            self._scaled[source.cacheKey()] = scaled
        return scaled

    def mousePressEvent(self, event: QMouseEvent) -> None:
        handle = self.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta:
            self.set_scale(self._scale + (SCALE_STEP if delta > 0 else -SCALE_STEP))

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._bus.context_menu_requested.emit(event.globalPos())

    def moveEvent(self, event: QMoveEvent) -> None:
        self._save_timer.start()

    def showEvent(self, event: QShowEvent) -> None:
        self._animator.start()

    def hideEvent(self, event: QHideEvent) -> None:
        self._animator.stop()
