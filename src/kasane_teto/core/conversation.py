"""Orquesta cada turno de conversación sin bloquear el hilo de la interfaz."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from kasane_teto.ai.llm_client import GenerationParams, LLMClient, LLMRequestError
from kasane_teto.ai.llm_process import LLMStartError
from kasane_teto.character.states import PetState
from kasane_teto.core.events import EventBus
from kasane_teto.core.resource_manager import ResourceManager
from kasane_teto.core.settings import Settings
from kasane_teto.memory.knowledge import Entry, KnowledgeBase, is_follow_up, wants_opinion
from kasane_teto.personality.emotion_parser import RESPONSE_GRAMMAR, EmotionParser
from kasane_teto.personality.prompt_builder import (
    build_messages,
    SEARCH_DONE,
    knowledge_block,
    load_system_prompt,
)
from kasane_teto.tools.web_lookup import (
    MusicLookup,
    WebQuery,
    WebResult,
    asks_to_search,
    bare_topic,
    parse_query,
    search_again_query,
)

MAX_HISTORY_MESSAGES = 30
KEPT_HISTORY_MESSAGES = 11
EMOTION_HOLD_MS = 4000
TRUNCATED_NOTICE = "…\n(Respuesta cortada por longitud: pídeme que continúe.)"
WEB_FAILED_NOTICE = "\n(No pude consultar VocaDB: he respondido sin esos datos.)"
EMPTY_ANSWER_MESSAGE = "Me he quedado en blanco. ¿Me lo repites?"
WEB_OFF_NOTICE = "\n(La búsqueda en VocaDB está apagada: actívala en Configuración.)"

log = logging.getLogger(__name__)


class _TaskSignals(QObject):
    status = Signal(str)
    state = Signal(PetState)
    token = Signal(str)
    notice = Signal(str)
    finished = Signal(str)
    failed = Signal(str)


class _GenerationTask(QRunnable):
    def __init__(
        self,
        resources: ResourceManager,
        compose: Callable[[WebResult], list[dict[str, str]]],
        params: GenerationParams,
        cancel: threading.Event,
        web_search: Callable[[], WebResult] | None = None,
        extra_notice: str = "",
    ) -> None:
        super().__init__()
        self._extra_notice = extra_notice
        self.signals = _TaskSignals()
        self._resources = resources
        self._compose = compose
        self._params = params
        self._cancel = cancel
        self._web_search = web_search

    def run(self) -> None:
        try:
            web = WebResult()
            if self._web_search is not None:
                self.signals.status.emit("Buscando en VocaDB…")
                web = self._web_search()
                if self._cancel.is_set():
                    self.signals.status.emit("")
                    self.signals.finished.emit("")
                    return
            messages = self._compose(web)
            self.signals.status.emit("Despertando a Teto…")
            process = self._resources.ensure_loaded()
            self.signals.status.emit("")
            text = self._generate(process.base_url, process.api_key, messages)
            if not text and not self._cancel.is_set():
                self.signals.failed.emit(EMPTY_ANSWER_MESSAGE)
                return
            if text:
                self._announce_sources(web)
                if self._extra_notice:
                    self.signals.notice.emit(self._extra_notice)
            self.signals.finished.emit(text)
        except LLMStartError as exc:
            log.error("La IA no pudo arrancar: %s", exc)
            self.signals.failed.emit("No pude cargar la IA. Revisa los modelos en la carpeta models.")
        except LLMRequestError as exc:
            log.error("Fallo al generar: %s", exc)
            self.signals.failed.emit("Se me cortó la respuesta. ¿Lo intentas de nuevo?")
        except Exception:
            log.exception("Error inesperado al generar")
            self.signals.failed.emit("Algo salió mal al responder.")

    def _announce_sources(self, web: WebResult) -> None:
        """La licencia de VocaDB pide atribución con enlace; va solo al chat, no a la voz."""
        if web.failed:
            self.signals.notice.emit(WEB_FAILED_NOTICE)
        elif web.sources:
            note = f"{web.note} " if web.note else ""
            self.signals.notice.emit(f"\n({note}Datos de VocaDB: {' · '.join(web.sources)})")

    def _generate(
        self, base_url: str, api_key: str, messages: list[dict[str, str]]
    ) -> str:
        client = LLMClient(base_url, api_key)
        parser = EmotionParser()
        parts: list[str] = []
        announced = False
        for chunk in client.stream_chat(messages, self._params, self._cancel):
            text = parser.feed(chunk)
            if not text:
                continue
            if not announced:
                self.signals.state.emit(parser.emotion or PetState.SPEAKING)
                announced = True
            parts.append(text)
            self.signals.token.emit(text)
        tail = parser.finish()
        if tail:
            parts.append(tail)
            self.signals.token.emit(tail)
        if client.finish_reason == "length":
            self.signals.notice.emit(TRUNCATED_NOTICE)
        return "".join(parts).strip()


class ConversationService(QObject):
    def __init__(
        self,
        bus: EventBus,
        resources: ResourceManager,
        settings: Settings,
        knowledge: KnowledgeBase,
        web: MusicLookup | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._resources = resources
        self._settings = settings
        self._knowledge = knowledge
        self._web = web
        self._last_web = WebResult()
        self._system_prompt = load_system_prompt()
        self._context_size = int(settings.get("ai.context_size", 4096))
        self._params = GenerationParams(
            max_tokens=int(settings.get("ai.max_tokens", 200)),
            temperature=float(settings.get("ai.temperature", 0.3)),
            repeat_penalty=float(settings.get("ai.repeat_penalty", 1.05)),
            grammar=RESPONSE_GRAMMAR,
        )
        self._history: list[dict[str, str]] = []
        self._cancel: threading.Event | None = None

        self._rest_timer = QTimer(self)
        self._rest_timer.setSingleShot(True)
        self._rest_timer.setInterval(EMOTION_HOLD_MS)
        self._rest_timer.timeout.connect(
            lambda: bus.pet_state_requested.emit(PetState.IDLE)
        )

        self._speaking = False
        bus.user_message.connect(self._on_user_message)
        bus.generation_stop_requested.connect(self._on_stop)
        bus.speech_active.connect(self._on_speech_active)
        bus.web_enabled_requested.connect(self._set_web_enabled)

    @property
    def is_busy(self) -> bool:
        return self._cancel is not None

    @property
    def web_enabled(self) -> bool:
        return self._web is not None and bool(self._settings.get("web.enabled", False))

    def _on_user_message(self, text: str) -> None:
        text = text.strip()
        if not text or self.is_busy:
            return
        self._rest_timer.stop()
        self._history.append({"role": "user", "content": text})
        # Se recorta de golpe: quitar un turno cada vez cambiaría el inicio de la conversación
        # y el servidor tendría que reprocesarla entera en todos los turnos siguientes.
        if len(self._history) > MAX_HISTORY_MESSAGES:
            self._history = self._history[-KEPT_HISTORY_MESSAGES:]
        entries = self._relevant_knowledge()
        self._cancel = threading.Event()
        self._resources.set_busy(True)
        self._bus.pet_state_requested.emit(PetState.THINKING)

        task = _GenerationTask(
            self._resources,
            partial(self._compose, text, entries),
            self._params,
            self._cancel,
            self._web_search_for(text),
            WEB_OFF_NOTICE if self._search_would_help(text) else "",
        )
        task.signals.status.connect(self._bus.assistant_status)
        task.signals.state.connect(self._bus.pet_state_requested)
        task.signals.token.connect(self._bus.assistant_token)
        task.signals.notice.connect(self._bus.assistant_notice)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        self._task_signals = task.signals
        QThreadPool.globalInstance().start(task)

    def _relevant_knowledge(self) -> list[Entry]:
        """Un nombre citado manda; el tema anterior solo sigue en preguntas de seguimiento."""
        user_messages = [m["content"] for m in self._history if m["role"] == "user"]
        current = user_messages[-1]
        entries = self._named_entries(current)
        if not entries and len(user_messages) > 1 and is_follow_up(current):
            entries = self._knowledge.by_name(user_messages[-2])
        if entries or self._continues_web_topic(current):
            return entries
        return self._knowledge.by_keywords(current)

    def _named_entries(self, text: str) -> list[Entry]:
        """Fichas citadas por su nombre o por uno parecido, como los que deforma la voz."""
        entries = self._knowledge.by_name(text)
        if entries:
            return entries
        query = parse_query(text)
        topic = query.topic if query is not None else bare_topic(text)
        return self._knowledge.by_similar_name(topic) if topic else []

    def _continues_web_topic(self, text: str) -> bool:
        """Una pregunta de seguimiento no debe activar fichas por una palabra suelta."""
        return (
            self.web_enabled
            and bool(self._last_web.facts)
            and is_follow_up(text)
            and parse_query(text) is None
            and not self._named_entries(text)
        )

    def _web_query(self, text: str) -> WebQuery | None:
        user_messages = [m["content"] for m in self._history if m["role"] == "user"]
        previous = user_messages[-2] if len(user_messages) > 1 else ""
        return search_again_query(text, previous) or parse_query(text)

    def _web_search_for(self, text: str) -> Callable[[], WebResult] | None:
        """Las fichas locales mandan: a Internet solo va lo que ellas no resuelven."""
        if not self.web_enabled or self._web is None:
            return None
        query = self._web_query(text)
        if query is None:
            if not self._continues_web_topic(text):
                return None
            last = self._last_web
            return lambda: last
        if not (query.wants_songs or query.explicit) and self._knows_topic(query.topic):
            return None
        return partial(self._search_web, query)

    def _search_would_help(self, text: str) -> bool:
        """Sin este aviso, con la búsqueda apagada parece que Teto no conoce a nadie."""
        if self._web is None or self.web_enabled:
            return False
        query = parse_query(text)
        return query is not None and (query.wants_songs or not self._knows_topic(query.topic))

    def _knows_topic(self, topic: str) -> bool:
        """Decide el nombre preguntado: "Kikuo, el de Vocaloid" no va sobre Vocaloid."""
        return bool(self._knowledge.by_name(topic) or self._knowledge.by_similar_name(topic))

    def _search_web(self, query: WebQuery) -> WebResult:
        assert self._web is not None
        return self._web.search(query)

    def _compose(
        self, text: str, entries: list[Entry], web: WebResult
    ) -> list[dict[str, str]]:
        """Corre en el hilo de la tarea: el historial no cambia mientras el turno está activo."""
        self._last_web = web
        query = parse_query(text)
        if web.sources and query is not None and not self._knows_topic(query.topic):
            entries = []
        block = knowledge_block(entries, wants_opinion(text), web.facts)
        if web.sources and asks_to_search(text):
            block += SEARCH_DONE
        return build_messages(
            self._system_prompt,
            self._history,
            self._context_size,
            self._params.max_tokens,
            block,
        )

    def _set_web_enabled(self, enabled: bool) -> None:
        self._settings.set("web.enabled", enabled)
        self._last_web = WebResult()

    def _on_stop(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def _on_finished(self, text: str) -> None:
        if text:
            self._history.append({"role": "assistant", "content": text})
        else:
            self._history.pop()
        self._end_turn()
        self._bus.assistant_done.emit()

    def _on_failed(self, message: str) -> None:
        self._history.pop()
        self._end_turn()
        self._bus.pet_state_requested.emit(PetState.CONFUSED)
        self._bus.assistant_error.emit(message)

    def _on_speech_active(self, active: bool) -> None:
        """La mascota mantiene su emoción mientras Teto habla."""
        self._speaking = active
        if active:
            self._rest_timer.stop()
        elif not self.is_busy:
            self._rest_timer.start()

    def _end_turn(self) -> None:
        self._cancel = None
        self._resources.set_busy(False)
        if not self._speaking:
            self._rest_timer.start()
