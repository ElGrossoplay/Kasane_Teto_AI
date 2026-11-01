"""Recuerdos e historial en SQLite. Solo escribe lo que el usuario ha aceptado guardar."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Concatenate, ParamSpec, TypeVar

from kasane_teto.memory.knowledge import normalize

MAX_CONTENT_CHARS = 300
MIN_TERM_LENGTH = 4
MIN_STEM_LENGTH = 4
STEM_CUT = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, content='memories', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

# Palabras de la pregunta que no ayudan a encontrar un recuerdo.
_STOPWORDS = frozenset(
    "como cual cuales cuando donde quien quienes para pero porque sobre esta este esto esos "
    "esas tiene tienen tengo sabes dime cuentame recuerdas acuerdas hola eres teto".split()
)

# Sin primera persona hablan de otros: "¿Cómo te llamas?" no debe sacar "Me llamo Diego".
_FIRST_PERSON = frozenset("yo mi mis me".split())
_PERSONAL_ONLY = frozenset(
    "llamo llama llamas llaman nombre gusta gustan gustas encanta encantan "
    "favorito favorita favoritos favoritas".split()
)

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class MemoryStoreError(Exception):
    """La base de datos de memoria no está disponible."""


def _guarded(method: Callable[Concatenate[MemoryStore, P], R]) -> Callable[Concatenate[MemoryStore, P], R]:
    def wrapper(self: MemoryStore, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(self, *args, **kwargs)
        except sqlite3.Error as exc:
            raise MemoryStoreError(str(exc)) from exc

    return wrapper


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    content: str
    created_at: float


@dataclass(frozen=True)
class ConversationInfo:
    id: int
    started_at: float
    messages: int


@dataclass(frozen=True)
class StoredMessage:
    role: str
    content: str
    created_at: float


def _clean(content: str) -> str:
    return " ".join(content.split())[:MAX_CONTENT_CHARS]


def _match_expression(text: str) -> str:
    """Busca por raíz de palabra: "llamo" debe encontrar "se llama"."""
    words = re.findall(r"\w+", normalize(text))
    speaks_about_self = _FIRST_PERSON.intersection(words)
    stems = set()
    for word in words:
        if len(word) < MIN_TERM_LENGTH or word in _STOPWORDS:
            continue
        if word in _PERSONAL_ONLY and not speaks_about_self:
            continue
        stems.add(word[: max(MIN_STEM_LENGTH, len(word) - STEM_CUT)])
    return " OR ".join(f'"{stem}"*' for stem in sorted(stems))


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._prepare()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path)
        try:
            # Lo borrado no debe quedar legible dentro del archivo.
            db.execute("PRAGMA secure_delete = ON")
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    @_guarded
    def _prepare(self) -> None:
        with self._connect() as db:
            db.executescript(_SCHEMA)

    @_guarded
    def add(self, kind: str, content: str, source: str = "chat") -> int:
        now = time.time()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO memories (kind, content, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, _clean(content), source, now, now),
            )
            return int(cursor.lastrowid or 0)

    @staticmethod
    def _purge_search_index(db: sqlite3.Connection) -> None:
        """Sin esto, el índice FTS conserva el texto borrado dentro del archivo."""
        db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")

    @_guarded
    def update(self, memory_id: int, content: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                (_clean(content), time.time(), memory_id),
            )
            self._purge_search_index(db)

    @_guarded
    def delete(self, memory_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._purge_search_index(db)

    @_guarded
    def clear(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM memories")
            self._purge_search_index(db)

    @_guarded
    def all(self, query: str = "") -> list[Memory]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, kind, content, created_at FROM memories ORDER BY created_at DESC, id DESC"
            ).fetchall()
        memories = [Memory(*row) for row in rows]
        wanted = normalize(query.strip())
        return [m for m in memories if wanted in normalize(m.content)] if wanted else memories

    def recent(self, limit: int) -> list[Memory]:
        return self.all()[:limit]

    def contains(self, content: str) -> bool:
        wanted = normalize(_clean(content))
        return any(normalize(memory.content) == wanted for memory in self.all())

    @_guarded
    def search(self, text: str, limit: int) -> list[Memory]:
        match = _match_expression(text)
        if not match:
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT m.id, m.kind, m.content, m.created_at FROM memories_fts f "
                "JOIN memories m ON m.id = f.rowid "
                "WHERE memories_fts MATCH ? ORDER BY f.rank LIMIT ?",
                (match, limit),
            ).fetchall()
        return [Memory(*row) for row in rows]

    @_guarded
    def start_conversation(self) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO conversations (started_at) VALUES (?)", (time.time(),))
            return int(cursor.lastrowid or 0)

    @_guarded
    def add_message(self, conversation_id: int, role: str, content: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, time.time()),
            )

    @_guarded
    def conversations(self) -> list[ConversationInfo]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.id, c.started_at, COUNT(m.id) FROM conversations c "
                "LEFT JOIN messages m ON m.conversation_id = c.id "
                "GROUP BY c.id ORDER BY c.started_at DESC, c.id DESC"
            ).fetchall()
        return [ConversationInfo(*row) for row in rows]

    @_guarded
    def messages(self, conversation_id: int) -> list[StoredMessage]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [StoredMessage(*row) for row in rows]

    @_guarded
    def delete_conversation(self, conversation_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    @_guarded
    def clear_history(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM conversations")
