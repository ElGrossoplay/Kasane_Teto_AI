"""Detecta lo que merece recordarse. Solo propone: guardar exige que el usuario lo acepte."""

from __future__ import annotations

import re
from dataclasses import dataclass

from kasane_teto.memory.knowledge import normalize

MIN_CONTENT_CHARS = 3
MAX_CONTENT_CHARS = 200

_EXPLICIT = re.compile(
    r"\b(?:recu[eé]rda(?:me)?|acu[eé]rdate(?:\s+de)?|no\s+(?:te\s+)?olvides(?:\s+de)?"
    r"|apunta|anota|guarda|memoriza)\s+(?:que\s+|esto\s*:\s*)(?P<content>.+)",
    re.IGNORECASE | re.DOTALL,
)
_PREFERENCE = re.compile(
    r"^(?:(?:no\s+)?me\s+(?:gusta|gustan|encanta|encantan)|odio|detesto|adoro|prefiero)\s+\S"
    r"|^mis?\s+[\w ]{1,30}\s+favorit[oa]s?\s+(?:es|son)\s+\S",
    re.IGNORECASE,
)
_FACT = re.compile(
    r"^tengo\s+\d{1,3}\s+a[nñ]os\b"
    r"|^(?:me\s+llamo|mi\s+nombre\s+es|soy\s+de|vivo\s+en|trabajo\s+(?:en|de|como)|estudio"
    r"|mi\s+cumplea[nñ]os\s+es|mi\s+[\w ]{1,25}\s+se\s+llama)\s+\S",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?\n])\s+")
_SECRET = re.compile(
    r"contrase[nñ]a|password|clave|\bpin\b|tarjeta|cuenta\s+bancaria|iban|\bdni\b|pasaporte"
    r"|token|\d{6,}|\S+@\S+\.\S+",
    re.IGNORECASE,
)
# Una respuesta vale si todas sus palabras son de esta lista: "Sí, hazlo" sí, "Sí que me gusta" no.
# "ti" es como la voz transcribe a veces "sí".
_YES_WORDS = frozenset(
    "si ti claro vale ok okay dale adelante hazlo de acuerdo por favor guardalo recuerdalo "
    "abrelo abrela cierralo cierrala venga perfecto bien".split()
)
_YES_FIRST = _YES_WORDS - frozenset("de acuerdo por favor bien".split()) | {"de"}
_NO_WORDS = frozenset(
    "no gracias lo guardes recuerdes hagas abras cierres mejor olvidalo dejalo nada cancela".split()
)
_NO_FIRST = frozenset("no mejor olvidalo dejalo cancela".split())
_ASKS_MEMORIES = re.compile(
    r"\bqu[eé]\s+(?:recuerdas|sabes|tienes\s+guardado|has\s+guardado)\s+(?:de|sobre)\s+m[ií]\b"
    r"|\bqu[eé]\s+(?:cosas\s+)?recuerdas\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Proposal:
    kind: str
    content: str
    explicit: bool = False


def _tidy(text: str) -> str:
    return " ".join(text.split()).strip(" .,;:!¡¿")


def has_secret(text: str) -> bool:
    return _SECRET.search(text) is not None


def _usable(content: str) -> bool:
    return MIN_CONTENT_CHARS <= len(content) <= MAX_CONTENT_CHARS and not has_secret(content)


def detect_proposal(text: str) -> Proposal | None:
    """Pedido expreso o frase clara sobre el usuario. Las contraseñas nunca se proponen."""
    explicit = _EXPLICIT.search(text)
    if explicit is not None:
        content = _tidy(explicit.group("content"))
        return Proposal("hecho", content, explicit=True) if _usable(content) else None
    for sentence in _SENTENCE_END.split(text.strip()):
        if sentence.rstrip().endswith("?") or "¿" in sentence:
            continue
        content = _tidy(sentence)
        if not _usable(content):
            continue
        if _PREFERENCE.search(content):
            return Proposal("preferencia", content)
        if _FACT.search(content):
            return Proposal("hecho", content)
    return None


def read_answer(text: str) -> bool | None:
    """Sí o no a una propuesta. Cualquier otra frase significa que el usuario cambió de tema."""
    words = re.findall(r"\w+", normalize(text))
    if not words:
        return None
    if words[0] in _YES_FIRST and _YES_WORDS.issuperset(words):
        return True
    return False if words[0] in _NO_FIRST and _NO_WORDS.issuperset(words) else None


def asks_memories(text: str) -> bool:
    return _ASKS_MEMORIES.search(text) is not None
