"""Corrige en el texto los errores que el reconocimiento de voz comete siempre igual.

Medido con 12 grabaciones de Diego: da mejor resultado que dar ejemplos al reconocedor, porque
esos ejemplos deformaban otras frases ("¿Quién me recomiendas…") y a veces los repetía como si
se hubieran dicho.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_SPELLING = (
    (re.compile(r"\bkienes\b", re.IGNORECASE), "quién es"),
    (re.compile(r"\bkien\b", re.IGNORECASE), "quién"),
)
_WHO_IS = re.compile(
    r"^\W*(?:dime\s+)?(?:qui[eé]nes|qui[eé]n\s+es)\s+(?!son\b|fueron\b|eran\b)(?P<rest>.+?)\W*$",
    re.IGNORECASE | re.DOTALL,
)
_MISHEARD_WHO_IS = re.compile(
    r"^\W*gen\s+es\s+(?!un\b|una\b|el\b|la\b|mi\b|muy\b|m[aá]s\b)(?P<rest>.+?)\W*$",
    re.IGNORECASE | re.DOTALL,
)


def fix_question(text: str) -> str:
    """Convierte "Kienes Mili." en "¿Quién es Mili?"; el resto del texto no cambia."""
    for pattern, replacement in _SPELLING:
        text = pattern.sub(replacement, text)
    match = _WHO_IS.match(text) or _MISHEARD_WHO_IS.match(text)
    return f"¿Quién es {match.group('rest')}?" if match else text


def fix_transcript(text: str, correct_names: Callable[[str], str]) -> str:
    return correct_names(fix_question(text))
