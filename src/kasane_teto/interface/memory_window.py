"""Panel para ver, buscar, editar y borrar los recuerdos y el historial."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from kasane_teto.memory.store import MemoryStore, MemoryStoreError

ROLE_LABELS = {"user": "Tú", "assistant": "Teto"}

log = logging.getLogger(__name__)


class MemoryWindow(QDialog):
    def __init__(self, store: MemoryStore) -> None:
        super().__init__()
        self._store = store
        self.setWindowTitle("Memoria de Teto")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(560, 460)

        tabs = QTabWidget()
        tabs.addTab(self._build_memories_tab(), "Recuerdos")
        tabs.addTab(self._build_history_tab(), "Historial")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        self._reload_memories()
        self._reload_conversations()

    def _build_memories_tab(self) -> QWidget:
        self._search = QLineEdit(placeholderText="Buscar en los recuerdos…")
        self._search.textChanged.connect(self._reload_memories)
        self._memories = QListWidget()
        self._memories.setWordWrap(True)

        add = QPushButton("Añadir…")
        edit = QPushButton("Editar…")
        delete = QPushButton("Borrar")
        clear = QPushButton("Borrar todo")
        add.clicked.connect(self._add_memory)
        edit.clicked.connect(self._edit_memory)
        delete.clicked.connect(self._delete_memory)
        clear.clicked.connect(self._clear_memories)

        buttons = QHBoxLayout()
        for button in (add, edit, delete, clear):
            buttons.addWidget(button)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._search)
        layout.addWidget(self._memories)
        layout.addLayout(buttons)
        return tab

    def _build_history_tab(self) -> QWidget:
        self._conversations = QListWidget()
        self._conversations.currentItemChanged.connect(self._show_conversation)
        self._messages = QPlainTextEdit(readOnly=True)

        delete = QPushButton("Borrar conversación")
        clear = QPushButton("Borrar todo el historial")
        delete.clicked.connect(self._delete_conversation)
        clear.clicked.connect(self._clear_history)

        buttons = QHBoxLayout()
        buttons.addWidget(delete)
        buttons.addWidget(clear)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._conversations, 1)
        layout.addWidget(self._messages, 2)
        layout.addLayout(buttons)
        return tab

    def _attempt(self, action: Callable[[], None]) -> None:
        try:
            action()
        except MemoryStoreError as exc:
            log.error("Memoria no disponible: %s", exc)
            QMessageBox.warning(self, "Memoria", "No se pudo acceder a la memoria.")

    def _confirm(self, question: str) -> bool:
        answer = QMessageBox.question(self, "Memoria", question)
        return answer == QMessageBox.StandardButton.Yes

    def _reload_memories(self) -> None:
        def reload() -> None:
            self._memories.clear()
            for memory in self._store.all(self._search.text()):
                item = QListWidgetItem(memory.content)
                item.setData(Qt.ItemDataRole.UserRole, memory.id)
                self._memories.addItem(item)

        self._attempt(reload)

    def _selected_memory(self) -> QListWidgetItem | None:
        return self._memories.currentItem()

    def _add_memory(self) -> None:
        text, accepted = QInputDialog.getMultiLineText(self, "Añadir recuerdo", "Recuerdo:")
        if accepted and text.strip():
            self._attempt(lambda: self._store.add("hecho", text, "panel"))
            self._reload_memories()

    def _edit_memory(self) -> None:
        item = self._selected_memory()
        if item is None:
            return
        memory_id = int(item.data(Qt.ItemDataRole.UserRole))
        text, accepted = QInputDialog.getMultiLineText(
            self, "Editar recuerdo", "Recuerdo:", item.text()
        )
        if accepted and text.strip():
            self._attempt(lambda: self._store.update(memory_id, text))
            self._reload_memories()

    def _delete_memory(self) -> None:
        item = self._selected_memory()
        if item is None or not self._confirm("¿Borrar este recuerdo?"):
            return
        memory_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._attempt(lambda: self._store.delete(memory_id))
        self._reload_memories()

    def _clear_memories(self) -> None:
        if self._confirm("¿Borrar todos los recuerdos? No se puede deshacer."):
            self._attempt(self._store.clear)
            self._reload_memories()

    def _reload_conversations(self) -> None:
        def reload() -> None:
            self._conversations.clear()
            self._messages.clear()
            for conversation in self._store.conversations():
                date = datetime.fromtimestamp(conversation.started_at).strftime("%d/%m/%Y %H:%M")
                item = QListWidgetItem(f"{date} · {conversation.messages} mensajes")
                item.setData(Qt.ItemDataRole.UserRole, conversation.id)
                self._conversations.addItem(item)

        self._attempt(reload)

    def _show_conversation(self, item: QListWidgetItem | None) -> None:
        self._messages.clear()
        if item is None:
            return
        conversation_id = int(item.data(Qt.ItemDataRole.UserRole))

        def show() -> None:
            lines = [
                f"{ROLE_LABELS.get(m.role, m.role)}: {m.content}\n"
                for m in self._store.messages(conversation_id)
            ]
            self._messages.setPlainText("\n".join(lines))

        self._attempt(show)

    def _delete_conversation(self) -> None:
        item = self._conversations.currentItem()
        if item is None or not self._confirm("¿Borrar esta conversación?"):
            return
        conversation_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._attempt(lambda: self._store.delete_conversation(conversation_id))
        self._reload_conversations()

    def _clear_history(self) -> None:
        if self._confirm("¿Borrar todo el historial? No se puede deshacer."):
            self._attempt(self._store.clear_history)
            self._reload_conversations()
