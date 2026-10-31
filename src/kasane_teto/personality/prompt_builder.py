"""Monta los mensajes del modelo respetando el límite de contexto."""

from __future__ import annotations

from pathlib import Path

CHARS_PER_TOKEN = 3


def load_system_prompt() -> str:
    path = Path(__file__).resolve().parent / "prompts" / "teto.txt"
    return path.read_text(encoding="utf-8")


def estimate_tokens(text: str) -> int:
    """Estimación prudente: en español suele haber más de 3 caracteres por token."""
    return len(text) // CHARS_PER_TOKEN + 4


def build_messages(
    system_prompt: str,
    history: list[dict[str, str]],
    context_size: int,
    reserved_tokens: int,
) -> list[dict[str, str]]:
    """Conserva los turnos más recientes que quepan; el último siempre se incluye."""
    budget = context_size - reserved_tokens - estimate_tokens(system_prompt)
    kept: list[dict[str, str]] = []
    for message in reversed(history):
        cost = estimate_tokens(message["content"])
        if kept and cost > budget:
            break
        budget -= cost
        kept.append(message)
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return [{"role": "system", "content": system_prompt}, *kept]
