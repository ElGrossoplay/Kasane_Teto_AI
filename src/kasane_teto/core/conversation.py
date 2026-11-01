"""Orquesta cada turno de conversación sin bloquear el hilo de la interfaz."""

from __future__ import annotations

import logging
import threading

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
    knowledge_block,
    load_system_prompt,
)

MAX_HISTORY_MESSAGES = 30
KEPT_HISTORY_MESSAGES = 11
EMOTION_HOLD_MS = 4000
TRUNCATED_NOTICE = "…\n(Respuesta cortada por longitud: pídeme que continúe.)"

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
        messages: list[dict[str, str]],
        params: GenerationParams,
        cancel: threading.Event,
    ) -> None:
        super().__init__()
        self.signals = _TaskSignals()
        self._resources = resources
        self._messages = messages
        self._params = params
        self._cancel = cancel

    def run(self) -> None:
        try:
            self.signals.status.emit("Despertando a Teto…")
            process = self._resources.ensure_loaded()
            self.signals.status.emit("")
            self.signals.finished.emit(self._generate(process.base_url, process.api_key))
        except LLMStartError as exc:
            log.error("La IA no pudo arrancar: %s", exc)
            self.signals.failed.emit("No pude cargar la IA. Revisa los modelos en la carpeta models.")
        except LLMRequestError as exc:
            log.error("Fallo al generar: %s", exc)
            self.signals.failed.emit("Se me cortó la respuesta. ¿Lo intentas de nuevo?")
        except Exception:
            log.exception("Error inesperado al generar")
            self.signals.failed.emit("Algo salió mal al responder.")

    def _generate(self, base_url: str, api_key: str) -> str:
        client = LLMClient(base_url, api_key)
        parser = EmotionParser()
        parts: list[str] = []
        announced = False
        for chunk in client.stream_chat(self._messages, self._params, self._cancel):
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._resources = resources
        self._knowledge = knowledge
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

    @property
    def is_busy(self) -> bool:
        return self._cancel is not None

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
        messages = build_messages(
            self._system_prompt,
            self._history,
            self._context_size,
            self._params.max_tokens,
            knowledge_block(self._relevant_knowledge(), wants_opinion(text)),
        )
        self._cancel = threading.Event()
        self._resources.set_busy(True)
        self._bus.pet_state_requested.emit(PetState.THINKING)

        task = _GenerationTask(self._resources, messages, self._params, self._cancel)
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
        entries = self._knowledge.by_name(current)
        if not entries and len(user_messages) > 1 and is_follow_up(current):
            entries = self._knowledge.by_name(user_messages[-2])
        return entries or self._knowledge.by_keywords(current)

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
