"""Conecta Teto con la aplicación de Discord del usuario. Las claves las escribe él."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from kasane_teto.tools.discord_rpc import DiscordError, DiscordVoice

STEPS = (
    "1. En discord.com/developers/applications crea una aplicación.\n"
    "2. En OAuth2 copia el Client ID y genera el Client Secret.\n"
    "3. En OAuth2, Redirects, añade http://127.0.0.1 y guarda.\n"
    "4. Pega aquí los dos datos con Discord abierto y acepta su ventana."
)
CONTACT_STEPS = (
    "Contactos: en Discord activa Ajustes, Avanzado, Modo desarrollador. Haz clic derecho en el chat "
    "de tu amigo, elige Copiar ID del canal (no el del usuario) y pégalo aquí con su nombre."
)


class _Signals(QObject):
    finished = Signal(str)


class _ConnectTask(QRunnable):
    def __init__(self, discord: DiscordVoice, client_id: str, secret: str) -> None:
        super().__init__()
        self.signals = _Signals()
        self._discord = discord
        self._client_id = client_id
        self._secret = secret

    def run(self) -> None:
        try:
            count = self._discord.authorize(self._client_id, self._secret)
            self.signals.finished.emit(f"Conectado: veo {count} canales de voz.")
        except DiscordError as exc:
            self.signals.finished.emit(str(exc))


class DiscordWindow(QDialog):
    def __init__(self, discord: DiscordVoice, parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self._discord = discord
        self._signals: _Signals | None = None
        self.setWindowTitle("Discord")

        steps = QLabel(STEPS)
        steps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._client_id = QLineEdit()
        self._secret = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self._connect = QPushButton("Conectar")
        self._forget = QPushButton("Olvidar esta conexión")
        self._status = QLabel(wordWrap=True)
        self._connect.clicked.connect(self._start)
        self._forget.clicked.connect(self._clear)
        self._forget.setEnabled(discord.is_configured)
        if discord.is_configured:
            self._status.setText("Discord ya está conectado.")

        self._contacts = QListWidget()
        self._contact_name = QLineEdit()
        self._contact_chat = QLineEdit()
        self._add_contact = QPushButton("Añadir contacto")
        self._remove_contact = QPushButton("Quitar el seleccionado")
        self._add_contact.clicked.connect(self._save_contact)
        self._remove_contact.clicked.connect(self._drop_contact)
        self._refresh_contacts()

        form = QFormLayout()
        form.addRow("Client ID", self._client_id)
        form.addRow("Client Secret", self._secret)
        contact_form = QFormLayout()
        contact_form.addRow("Nombre", self._contact_name)
        contact_form.addRow("ID del canal", self._contact_chat)
        layout = QVBoxLayout(self)
        layout.addWidget(steps)
        layout.addLayout(form)
        layout.addWidget(self._connect)
        layout.addWidget(self._forget)
        layout.addWidget(QLabel(CONTACT_STEPS, wordWrap=True))
        layout.addWidget(self._contacts)
        layout.addLayout(contact_form)
        layout.addWidget(self._add_contact)
        layout.addWidget(self._remove_contact)
        layout.addWidget(self._status)

    def _start(self) -> None:
        client_id, secret = self._client_id.text().strip(), self._secret.text().strip()
        if not client_id or not secret:
            self._status.setText("Faltan el Client ID o el Client Secret.")
            return
        self._connect.setEnabled(False)
        self._status.setText("Acepta la ventana que aparece en Discord…")
        task = _ConnectTask(self._discord, client_id, secret)
        task.signals.finished.connect(self._on_finished)
        self._signals = task.signals
        QThreadPool.globalInstance().start(task)

    def _on_finished(self, message: str) -> None:
        self._signals = None
        self._secret.clear()
        self._connect.setEnabled(True)
        self._forget.setEnabled(self._discord.is_configured)
        self._status.setText(message)

    def _clear(self) -> None:
        self._discord.forget()
        self._forget.setEnabled(False)
        self._refresh_contacts()
        self._status.setText("Conexión y contactos olvidados.")

    def _refresh_contacts(self) -> None:
        self._contacts.clear()
        self._contacts.addItems([contact.name for contact in self._discord.contacts()])

    def _save_contact(self) -> None:
        try:
            contact = self._discord.add_contact(self._contact_name.text(), self._contact_chat.text())
        except DiscordError as exc:
            self._status.setText(str(exc))
            return
        self._contact_name.clear()
        self._contact_chat.clear()
        self._refresh_contacts()
        self._status.setText(f"Guardado: {contact.name}.")

    def _drop_contact(self) -> None:
        item = self._contacts.currentItem()
        if item is not None:
            self._discord.remove_contact(item.text())
            self._refresh_contacts()
