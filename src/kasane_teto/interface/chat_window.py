"""Ventana de chat: solo habla con el EventBus, nunca con la IA."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kasane_teto.core.events import EventBus


class ChatWindow(QWidget):
    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self._bus = bus
        self._awaiting_first_token = False
        self._answering = False
        self.setWindowTitle("Hablar con Teto")
        self.resize(420, 520)

        self._log = QPlainTextEdit(readOnly=True)
        self._status = QLabel()
        self._input = QLineEdit(placeholderText="Escribe un mensaje…")
        self._send = QPushButton("Enviar")
        self._stop = QPushButton("Detener", enabled=False)
        self._talk = QPushButton("Hablar")
        self._talk.setToolTip("Mantén pulsado para hablar")

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
        layout.addWidget(self._log)
        layout.addWidget(self._status)
        layout.addWidget(self._proposal_bar)
        layout.addWidget(self._action_bar)
        layout.addLayout(row)

        self._input.returnPressed.connect(self._submit)
        self._send.clicked.connect(self._submit)
        self._stop.clicked.connect(lambda: bus.generation_stop_requested.emit())
        self._talk.pressed.connect(lambda: bus.listen_started.emit())
        self._talk.released.connect(lambda: bus.listen_stopped.emit())
        bus.assistant_status.connect(self._status.setText)
        bus.voice_status.connect(self._status.setText)
        bus.assistant_token.connect(self._on_token)
        bus.assistant_notice.connect(self._append)
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

    def _submit(self) -> None:
        text = self._input.text()
        if text.strip() and not self._stop.isEnabled():
            self._input.clear()
            self._send_text(text)

    def _send_text(self, text: str) -> None:
        text = text.strip()
        if not text or self._stop.isEnabled():
            return
        self._append(f"Tú: {text}\n")
        self._awaiting_first_token = True
        self._set_generating(True)
        self._bus.user_message.emit(text)

    def _on_token(self, text: str) -> None:
        # Sin turno en marcha es un comentario de Teto: no hubo mensaje antes.
        if self._awaiting_first_token or not self._answering:
            self._awaiting_first_token = False
            self._append("Teto: ")
        self._answering = True
        self._append(text)

    def _on_done(self) -> None:
        if not self._awaiting_first_token:
            self._append("\n\n")
        self._finish_turn()

    def _on_error(self, message: str) -> None:
        self._append(f"{message}\n\n" if self._awaiting_first_token else f"\n{message}\n\n")
        self._finish_turn()

    def _finish_turn(self) -> None:
        self._awaiting_first_token = False
        self._answering = False
        self._status.clear()
        self._set_generating(False)

    def _set_generating(self, generating: bool) -> None:
        self._send.setEnabled(not generating)
        self._stop.setEnabled(generating)

    def _append(self, text: str) -> None:
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(QTextCursor.MoveOperation.End)
