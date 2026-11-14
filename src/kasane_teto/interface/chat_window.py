"""Ventana de chat: solo habla con el EventBus, nunca con la IA."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QRect, Qt, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QGuiApplication,
    QHideEvent,
    QKeyEvent,
    QKeySequence,
    QShortcut,
    QShowEvent,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from kasane_teto.core.events import EventBus
from kasane_teto.core.settings import Settings
from kasane_teto.desktop.hotkey import CHAT, TALK
from kasane_teto.interface.theme import colors

DEFAULT_SIZE = (440, 560)
MAX_RECALLED = 30
READY_STATUS = "Lista"
_URL = re.compile(r"https?://[^\s)·]+")


class ChatWindow(QWidget):
    """Enter envía, Esc cierra, flecha arriba recupera lo último que escribiste."""

    visibility_changed = Signal()

    def __init__(self, bus: EventBus, settings: Settings | None = None) -> None:
        super().__init__()
        self._bus = bus
        self._settings = settings
        self._awaiting_first_token = False
        self._answering = False
        self._sent: list[str] = []
        self._recall = 0
        self.setWindowTitle("Hablar con Teto")
        self._restore_geometry()

        title = QLabel("Teto")
        title.setProperty("role", "title")
        self._status = QLabel(READY_STATUS)
        self._status.setProperty("role", "muted")
        clear = QPushButton("Limpiar")
        clear.setToolTip("Borra lo que se ve aquí; no borra recuerdos ni historial")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addWidget(self._status, 1)
        header.addWidget(clear)

        self._log = QTextBrowser()
        self._log.setOpenExternalLinks(True)
        self._input = QLineEdit(placeholderText="Escribe un mensaje…")
        self._input.installEventFilter(self)
        self._input.setToolTip(f"{CHAT.label} abre esta ventana desde cualquier sitio")
        self._send = QPushButton("Enviar")
        self._send.setProperty("primary", True)
        self._stop = QPushButton("Detener", enabled=False)
        self._stop.setToolTip("Corta la respuesta y la voz")
        self._talk = QPushButton("Hablar")
        self._talk.setToolTip(f"Mantén pulsado para hablar, o usa {TALK.label} desde cualquier ventana")

        self._proposal = QLabel(wordWrap=True)
        self._remember = QPushButton("Sí, recuérdalo")
        self._forget = QPushButton("No")
        self._remember.clicked.connect(lambda: bus.memory_answered.emit(True))
        self._forget.clicked.connect(lambda: bus.memory_answered.emit(False))
        self._proposal_bar = self._confirm_bar(self._proposal, self._remember, self._forget)

        self._action = QLabel(wordWrap=True)
        self._allow = QPushButton("Sí, hazlo")
        self._deny = QPushButton("No")
        self._allow.clicked.connect(lambda: bus.action_answered.emit(True))
        self._deny.clicked.connect(lambda: bus.action_answered.emit(False))
        self._action_bar = self._confirm_bar(self._action, self._allow, self._deny)

        row = QHBoxLayout()
        row.addWidget(self._input)
        row.addWidget(self._send)
        row.addWidget(self._talk)
        row.addWidget(self._stop)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._log, 1)
        layout.addWidget(self._proposal_bar)
        layout.addWidget(self._action_bar)
        layout.addLayout(row)

        self._input.returnPressed.connect(self._submit)
        self._send.clicked.connect(self._submit)
        self._stop.clicked.connect(lambda: bus.generation_stop_requested.emit())
        self._talk.pressed.connect(lambda: bus.listen_started.emit())
        self._talk.released.connect(lambda: bus.listen_stopped.emit())
        clear.clicked.connect(self._log.clear)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        bus.assistant_status.connect(self._set_status)
        bus.voice_status.connect(self._set_status)
        bus.assistant_token.connect(self._on_token)
        bus.assistant_notice.connect(self._on_notice)
        bus.assistant_done.connect(self._on_done)
        bus.assistant_error.connect(self._on_error)
        bus.transcript_ready.connect(self._send_text)
        bus.memory_proposed.connect(self._show_proposal)
        bus.action_proposed.connect(self._show_action)

    @staticmethod
    def _confirm_bar(label: QLabel, yes: QPushButton, no: QPushButton) -> QWidget:
        widget = QWidget()
        bar = QHBoxLayout(widget)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(label, 1)
        bar.addWidget(yes)
        bar.addWidget(no)
        widget.hide()
        return widget

    def _show_proposal(self, content: str) -> None:
        """Un texto vacío retira la propuesta."""
        self._proposal.setText(f"¿Quieres que recuerde esto? «{content}»")
        self._proposal_bar.setVisible(bool(content))
        if content:
            self._show_without_focus()

    def _show_action(self, summary: str) -> None:
        """Un texto vacío retira la pregunta."""
        self._action.setText(f"{summary}. ¿De acuerdo?")
        self._action_bar.setVisible(bool(summary))
        if summary:
            self._show_without_focus()

    def _show_without_focus(self) -> None:
        """Se abre sin quitar el foco a lo que estés haciendo."""
        if not self.isVisible():
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.show()

    def open(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        super().closeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        self.visibility_changed.emit()

    def hideEvent(self, event: QHideEvent) -> None:
        self.visibility_changed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Flechas arriba y abajo en la caja de texto: mensajes enviados antes."""
        if watched is self._input and isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            step = {Qt.Key.Key_Up: 1, Qt.Key.Key_Down: -1}.get(event.key())
            if step is not None and self._sent:
                self._recall = max(0, min(len(self._sent), self._recall + step))
                self._input.setText(self._sent[-self._recall] if self._recall else "")
                return True
        return super().eventFilter(watched, event)

    def _restore_geometry(self) -> None:
        saved = self._settings.get("chat.geometry") if self._settings is not None else None
        if isinstance(saved, list) and len(saved) == 4 and all(isinstance(v, int) for v in saved):
            x, y, width, height = saved
            wanted = QRect(x, y, max(320, width), max(300, height))
            # Si la pantalla donde estaba ya no existe, se abre donde Windows decida.
            if QGuiApplication.screenAt(wanted.center()) is not None:
                self.setGeometry(wanted)
                return
        self.resize(*DEFAULT_SIZE)

    def _save_geometry(self) -> None:
        if self._settings is not None:
            g = self.geometry()
            self._settings.set("chat.geometry", [g.x(), g.y(), g.width(), g.height()])

    def _submit(self) -> None:
        text = self._input.text()
        if text.strip() and not self._stop.isEnabled():
            self._input.clear()
            self._send_text(text)

    def _send_text(self, text: str) -> None:
        text = text.strip()
        if not text or self._stop.isEnabled():
            return
        self._sent = [*self._sent[-MAX_RECALLED + 1 :], text]
        self._recall = 0
        self._append("Tú: ", "user_name")
        self._append(f"{text}\n", "user")
        self._awaiting_first_token = True
        self._set_generating(True)
        self._bus.user_message.emit(text)

    def _on_token(self, text: str) -> None:
        # Sin turno en marcha es un comentario de Teto: no hubo mensaje antes.
        if self._awaiting_first_token or not self._answering:
            self._awaiting_first_token = False
            self._append("Teto: ", "teto_name")
        self._answering = True
        self._append(text, "teto")

    def _on_notice(self, text: str) -> None:
        self._append(text, "notice")

    def _on_done(self) -> None:
        if not self._awaiting_first_token:
            self._append("\n\n")
        self._finish_turn()

    def _on_error(self, message: str) -> None:
        self._append(
            f"{message}\n\n" if self._awaiting_first_token else f"\n{message}\n\n", "error"
        )
        self._finish_turn()

    def _finish_turn(self) -> None:
        self._awaiting_first_token = False
        self._answering = False
        self._set_status("")
        self._set_generating(False)

    def _set_status(self, text: str) -> None:
        self._status.setText(text or READY_STATUS)

    def _set_generating(self, generating: bool) -> None:
        self._send.setEnabled(not generating)
        self._stop.setEnabled(generating)

    @staticmethod
    def _format(kind: str) -> QTextCharFormat:
        """Quién habla se distingue por el color; los avisos van más pequeños y apagados."""
        c = colors()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(c.text))
        if kind in ("user", "user_name"):
            fmt.setForeground(QColor(c.muted))
        if kind == "teto_name":
            fmt.setForeground(QColor(c.accent_hover))
        if kind.endswith("_name"):
            fmt.setFontWeight(QFont.Weight.Bold)
        if kind in ("notice", "error"):
            fmt.setForeground(QColor(c.accent_hover if kind == "error" else c.muted))
            fmt.setFontItalic(kind == "notice")
            fmt.setFontPointSize(9)
        return fmt

    def _append(self, text: str, kind: str = "teto") -> None:
        """Añade texto al final; en los avisos, las direcciones web quedan como enlaces."""
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = self._format(kind)
        position = 0
        for match in _URL.finditer(text) if kind == "notice" else ():
            cursor.insertText(text[position : match.start()], fmt)
            link = QTextCharFormat(fmt)
            link.setAnchor(True)
            link.setAnchorHref(match.group())
            link.setFontUnderline(True)
            cursor.insertText(match.group(), link)
            position = match.end()
        cursor.insertText(text[position:], fmt)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()
