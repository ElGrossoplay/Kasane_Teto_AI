"""Cliente de la API compatible con OpenAI de llama-server, en streaming."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import httpx

CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 120.0

log = logging.getLogger(__name__)


class LLMRequestError(Exception):
    """La petición al modelo falló."""


@dataclass(frozen=True)
class GenerationParams:
    max_tokens: int
    temperature: float
    grammar: str | None = None


def parse_sse_lines(lines: Iterable[str]) -> Iterator[str]:
    """Extrae los fragmentos de texto de las líneas de un flujo SSE."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return
        try:
            choices = json.loads(payload).get("choices") or []
        except ValueError:
            log.warning("Fragmento SSE ilegible")
            continue
        for choice in choices:
            content = (choice.get("delta") or {}).get("content")
            if content:
                yield content


class LLMClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url
        self._api_key = api_key

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        params: GenerationParams,
        cancel: threading.Event,
    ) -> Iterator[str]:
        body = {
            "messages": messages,
            "max_tokens": params.max_tokens,
            "temperature": params.temperature,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if params.grammar:
            body["grammar"] = params.grammar
        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
        try:
            with httpx.Client(base_url=self._base_url, timeout=timeout) as client:
                with client.stream(
                    "POST", "/v1/chat/completions", json=body, headers=headers
                ) as response:
                    if response.status_code != 200:
                        raise LLMRequestError(f"Respuesta HTTP {response.status_code}")
                    for chunk in parse_sse_lines(response.iter_lines()):
                        if cancel.is_set():
                            return
                        yield chunk
        except httpx.HTTPError as exc:
            raise LLMRequestError(str(exc)) from exc
