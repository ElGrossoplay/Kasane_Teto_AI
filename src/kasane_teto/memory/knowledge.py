"""Base de conocimiento local de solo lectura, con búsqueda por nombres y FTS5."""

from __future__ import annotations

import logging
import re
import sqlite3
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_RESULTS = 3
MIN_TERM_LENGTH = 4

# Palabras demasiado comunes en este tema: buscarlas activaría fichas sin relación.
STOPWORDS = frozenset(
    "como cual cuales cuando donde quien quienes para pero porque sobre esta este esto "
    "esos esas tiene tienen sabes dime cuentame opinas piensas sera eres sois hola "
    "cancion canciones cantante cantantes personaje personajes vocaloid famosa famoso "
    "famosas famosos mejor mejores mucho muchos todo todos algo alguna alguno "
    "hace hizo creo creado voz voces nombre nombres significa significado".split()
)

MAX_FOLLOW_UP_WORDS = 5
_FOLLOW_UP_START = re.compile(r"y\s")
_FOLLOW_UP_WORDS = re.compile(r"\b(ella|ellas|ellos|esa|ese|aquella|aquel|sus?)\b")
_FOLLOW_UP_VERBS = re.compile(
    r"\b(tiene|tienen|salio|nacio|canta|cantan|hizo|opinas|sientes|piensas|cuando|donde)\b"
)

log = logging.getLogger(__name__)


class KnowledgeError(Exception):
    """Un archivo de conocimiento no es válido."""


@dataclass(frozen=True)
class Entry:
    id: str
    names: tuple[str, ...]
    facts: str
    reaction: str


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, conservando los caracteres japoneses."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    kept = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", kept)


def is_follow_up(text: str) -> bool:
    """Detecta preguntas que dependen del tema anterior, como "¿y cuándo salió?"."""
    query = re.sub(r"^\W+", "", normalize(text))
    if _FOLLOW_UP_START.match(query) or _FOLLOW_UP_WORDS.search(query):
        return True
    return len(query.split()) <= MAX_FOLLOW_UP_WORDS and bool(_FOLLOW_UP_VERBS.search(query))


def _name_pattern(name: str) -> re.Pattern[str]:
    """Exige palabra completa en alfabeto latino; el japonés no separa palabras."""
    text = normalize(name)
    start = r"(?<!\w)" if text[0].isascii() else ""
    end = r"(?!\w)" if text[-1].isascii() else ""
    return re.compile(start + re.escape(text) + end)


def _parse_file(path: Path) -> list[Entry]:
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise KnowledgeError(f"No se pudo leer {path.name}: {exc}") from exc
    entries = []
    for raw in data.get("ficha", []):
        entry_id, names, facts = raw.get("id"), raw.get("nombres"), raw.get("hechos")
        if not entry_id or not isinstance(names, list) or not names or not facts:
            raise KnowledgeError(f"Ficha incompleta en {path.name}: {entry_id or raw}")
        entries.append(
            Entry(str(entry_id), tuple(map(str, names)), str(facts), str(raw.get("reaccion", "")))
        )
    return entries


class KnowledgeBase:
    def __init__(self, entries: list[Entry]) -> None:
        self._entries = {entry.id: entry for entry in entries}
        if len(self._entries) != len(entries):
            raise KnowledgeError("Hay fichas con el mismo id")
        self._patterns = [
            (entry.id, _name_pattern(name)) for entry in entries for name in entry.names
        ]
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE VIRTUAL TABLE fichas USING fts5(id UNINDEXED, texto, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )
        self._db.executemany(
            "INSERT INTO fichas VALUES (?, ?)",
            [(e.id, normalize(" ".join((*e.names, e.facts)))) for e in entries],
        )

    @classmethod
    def load(cls, folder: Path) -> KnowledgeBase:
        entries: list[Entry] = []
        for path in sorted(folder.glob("*.toml")):
            entries.extend(_parse_file(path))
        log.info("Conocimiento cargado: %d fichas", len(entries))
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def vocabulary(self, max_chars: int = 500) -> str:
        """Nombres propios para que el reconocimiento de voz los entienda mejor."""
        words = ["Kasane Teto"]
        size = len(words[0])
        for entry in self._entries.values():
            name = entry.names[0]
            if size + len(name) + 2 > max_chars:
                break
            words.append(name)
            size += len(name) + 2
        return ", ".join(words)

    def search(self, text: str, limit: int = MAX_RESULTS) -> list[Entry]:
        """Prioriza los nombres citados; si no hay, busca por palabras clave."""
        return self.by_name(text, limit) or self.by_keywords(text, limit)

    def by_name(self, text: str, limit: int = MAX_RESULTS) -> list[Entry]:
        query = normalize(text)
        hits: dict[str, int] = {}
        for entry_id, pattern in self._patterns:
            match = pattern.search(query)
            if match and (entry_id not in hits or match.start() < hits[entry_id]):
                hits[entry_id] = match.start()
        ordered = sorted(hits, key=hits.__getitem__)
        return [self._entries[entry_id] for entry_id in ordered[:limit]]

    def by_keywords(self, text: str, limit: int = MAX_RESULTS) -> list[Entry]:
        query = normalize(text)
        return [self._entries[entry_id] for entry_id in self._search_terms(query, limit)]

    def _search_terms(self, query: str, limit: int) -> list[str]:
        terms = {
            word
            for word in re.findall(r"\w+", query)
            if len(word) >= MIN_TERM_LENGTH and word not in STOPWORDS
        }
        if not terms:
            return []
        match = " OR ".join(f'"{term}"' for term in sorted(terms))
        rows = self._db.execute(
            "SELECT id FROM fichas WHERE fichas MATCH ? ORDER BY rank LIMIT ?", (match, limit)
        )
        return [row[0] for row in rows]
