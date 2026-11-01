"""Extrae la etiqueta de emoción con la que empieza una respuesta en streaming."""

from __future__ import annotations

import re

from kasane_teto.character.states import PetState

MAX_TAG_LENGTH = 16

EMOTIONS: dict[str, PetState] = {
    "neutral": PetState.SPEAKING,
    "feliz": PetState.HAPPY,
    "sorprendida": PetState.SURPRISED,
    "confundida": PetState.CONFUSED,
    "enfadada": PetState.ANGRY,
    "aburrida": PetState.BORED,
}

_TAG = re.compile(r"^\s*\[([^\[\]]*)\]\s*")

# Gramática GBNF: exige una etiqueta válida al inicio y evita corchetes y emojis en el texto.
RESPONSE_GRAMMAR = (
    'root ::= "[" emotion "] " first text\n'
    "emotion ::= " + " | ".join(f'"{name}"' for name in EMOTIONS) + "\n"
    # El primer carácter es obligatorio: sin él, el modelo puede responder solo con la emoción.
    r"first ::= [^ \t\n\[\]☀-➿\U0001F000-\U0001FAFF]"
    "\n"
    r"text ::= [^\[\]☀-➿\U0001F000-\U0001FAFF]*"
    "\n"
)


class EmotionParser:
    def __init__(self) -> None:
        self._buffer = ""
        self._decided = False
        self.emotion: PetState | None = None

    def feed(self, chunk: str) -> str:
        """Devuelve el texto visible; retiene el inicio hasta saber si hay etiqueta."""
        if self._decided:
            return chunk
        self._buffer += chunk
        start = self._buffer.lstrip()
        if not start:
            return ""
        if not start.startswith("["):
            return self._release(start)
        match = _TAG.match(self._buffer)
        if match is None:
            if len(start) > MAX_TAG_LENGTH:
                return self._release(start)
            return ""
        rest = self._buffer[match.end():]
        if not rest:
            return ""
        self.emotion = EMOTIONS.get(match.group(1).strip().casefold())
        return self._release(rest)

    def finish(self) -> str:
        """Entrega lo retenido cuando el flujo termina sin más texto."""
        if self._decided:
            return ""
        match = _TAG.match(self._buffer)
        if match is not None:
            self.emotion = EMOTIONS.get(match.group(1).strip().casefold())
            return self._release(self._buffer[match.end():])
        return self._release(self._buffer.strip())

    def _release(self, text: str) -> str:
        self._decided = True
        self._buffer = ""
        return text
