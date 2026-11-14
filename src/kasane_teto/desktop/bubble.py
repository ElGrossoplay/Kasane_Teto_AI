"""Bocadillo sobre la mascota: lo que dice Teto se lee sin abrir el chat.

No recibe clics ni foco: lo que haya debajo sigue funcionando. Como la mascota, nunca se pone
encima de un juego.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from kasane_teto.interface.theme import colors

MAX_WIDTH = 300
MAX_CHARS = 280  # de una respuesta larga se ve el final, que es lo último que ha dicho
PADDING = 12
TAIL = 10
RADIUS = 12
BASE_SECONDS = 4.0
SECONDS_PER_CHAR = 0.05
MAX_SECONDS = 14.0
HEAD_OVERLAP = 0.04  # baja un poco sobre la ventana de la mascota, que tiene aire encima


def visible_tail(text: str, limit: int = MAX_CHARS) -> str:
    """El final del texto, cortado por una palabra entera."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    space = cut.find(" ")
    return "…" + (cut[space + 1 :] if 0 <= space < 40 else cut)


def reading_seconds(text: str) -> float:
    return min(MAX_SECONDS, BASE_SECONDS + SECONDS_PER_CHAR * len(text))


class SpeechBubble(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._status = ""
        self._anchor = QRect()
        self._enabled = True
        self._blocked = False
        self._tail_x = 0
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._label = QLabel(wordWrap=True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING + TAIL)
        layout.addWidget(self._label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.clear)

    @property
    def text(self) -> str:
        return self._label.text()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.clear()

    def set_blocked(self, blocked: bool) -> None:
        """Modo juego, mascota oculta o chat abierto: no se muestra."""
        self._blocked = blocked
        if blocked:
            self.hide()
        else:
            self._refresh()

    def set_on_top(self, on_top: bool) -> None:
        if on_top == bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        if visible:
            self.show()

    def set_anchor(self, pet: QRect) -> None:
        """Sigue a la mascota."""
        self._anchor = QRect(pet)
        if self.isVisible():
            self._place()

    def begin(self) -> None:
        """Empieza un turno: se borra lo anterior."""
        self._hide_timer.stop()
        self._text = ""
        self._refresh()

    def append(self, token: str) -> None:
        self._hide_timer.stop()
        self._text += token
        self._refresh()

    def say(self, text: str) -> None:
        """Un mensaje entero (un aviso o un error), que se retira solo."""
        self._text = text
        self._refresh()
        self.finish()

    def set_status(self, status: str) -> None:
        """«Pensando…», «Te escucho…»: solo se ve mientras no hay respuesta."""
        self._status = status
        self._refresh()

    def finish(self) -> None:
        self._status = ""
        if self._text.strip():
            self._hide_timer.start(round(1000 * reading_seconds(self._text)))
        else:
            self.clear()

    def clear(self) -> None:
        self._hide_timer.stop()
        self._text = ""
        self._status = ""
        self.hide()

    def _refresh(self) -> None:
        shown = visible_tail(self._text) or self._status
        if not shown or not self._enabled or self._blocked or self._anchor.isEmpty():
            self.hide()
            return
        if shown != self._label.text():
            self._label.setText(shown)
            # Sin esto, Qt parte en varias líneas un texto que cabría en una.
            wanted = self._label.fontMetrics().horizontalAdvance(shown) + 4
            self._label.setFixedWidth(min(MAX_WIDTH - 2 * PADDING, wanted))
            self._label.setStyleSheet(f"color: {colors().text};")
            self.adjustSize()
        self._place()
        if not self.isVisible():
            self.show()

    def _place(self) -> None:
        """Encima de la cabeza; si no cabe en la pantalla, se corre hacia dentro."""
        pet = self._anchor
        screen = QGuiApplication.screenAt(pet.center()) or QGuiApplication.primaryScreen()
        x = pet.center().x() - self.width() // 2
        y = pet.top() + round(pet.height() * HEAD_OVERLAP) - self.height()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = max(area.top(), y)
        tail_x = max(RADIUS + TAIL, min(pet.center().x() - x, self.width() - RADIUS - TAIL))
        if tail_x != self._tail_x:
            self._tail_x = tail_x
            self.update()
        self.move(QPoint(x, y))

    def paintEvent(self, event: QPaintEvent) -> None:
        c = colors()
        body = QRectF(0.5, 0.5, self.width() - 1, self.height() - TAIL - 1)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)
        tail = QPainterPath()
        tail.moveTo(self._tail_x - TAIL, body.bottom())
        tail.lineTo(self._tail_x, self.height() - 0.5)
        tail.lineTo(self._tail_x + TAIL, body.bottom())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(c.accent), 1.5))
        painter.setBrush(QColor(c.raised))
        painter.drawPath(path.united(tail))
