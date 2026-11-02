"""Orquesta cada turno de conversación sin bloquear el hilo de la interfaz."""

from __future__ import annotations

import logging
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from kasane_teto.ai.llm_client import GenerationParams, LLMClient, LLMRequestError
from kasane_teto.ai.llm_process import LLMStartError
from kasane_teto.character.states import PetState
from kasane_teto.core.events import EventBus
from kasane_teto.core.resource_manager import ResourceManager
from kasane_teto.core.settings import Settings
from kasane_teto.memory.knowledge import Entry, KnowledgeBase, is_follow_up, wants_opinion
from kasane_teto.memory.proposals import (
    Proposal,
    asks_memories,
    detect_proposal,
    has_secret,
    read_answer,
)
from kasane_teto.memory.store import MemoryStore, MemoryStoreError
from kasane_teto.personality.emotion_parser import RESPONSE_GRAMMAR, EmotionParser
from kasane_teto.personality.prompt_builder import (
    COMMENT_PROMPT,
    DOCUMENT_PROMPTS,
    DOCUMENT_SYSTEM,
    MESSAGE_PROMPT,
    SCREEN_PROMPT,
    SEARCH_DONE,
    build_messages,
    knowledge_block,
    load_system_prompt,
    system_prompt_for,
)
from kasane_teto.tools.documents import strip_preamble
from kasane_teto.tools.commands import (
    CHAT_MESSAGE,
    LOOK_AT_SCREEN,
    WRITE_DOCUMENT,
    Command,
    asks_open_things,
    parse_command,
)
from kasane_teto.tools.registry import Action, ActionRejected, ToolRegistry
from kasane_teto.tools.screen_capture import CaptureError, capture_screen_url
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
MEMORY_ASK_REPLY = "¿Lo guardo? Dime sí o no, o usa los botones."
MEMORY_SAVED_REPLY = "Hecho, lo recordaré."
MEMORY_DECLINED_REPLY = "Vale, no lo guardo."
MEMORY_FAILED_REPLY = "No he podido guardarlo. Revisa la memoria en el menú."
RECENT_MEMORIES = 8
OMITTED_MESSAGE = "(Mensaje omitido: parecía contener un dato sensible.)"
TOOLS_OFF_NOTICE = "\n(El control de Windows está apagado: actívalo en Configuración.)"
ACTION_CONFIRM_REPLY = "{summary}. ¿De acuerdo? Dime sí o no, o usa los botones."
ACTION_CANCELLED_REPLY = "Vale, no hago nada."
ACTION_EXPIRED_REPLY = "Ha pasado demasiado tiempo. Pídemelo otra vez."
ACTION_FAILED_REPLY = "No he podido hacerlo."
ACTION_TIMEOUT_SECONDS = 60.0
SCREEN_GAME_REPLY = "Hay un juego abierto: la pantalla no la miro, para no meterte en líos."
SCREEN_FAILED_REPLY = "No he podido capturar la pantalla."
VISION_UNAVAILABLE_MESSAGE = "No pude cargar la visión. Cierra lo que esté usando la GPU y repítelo."
DOCUMENT_SAVED_REPLY = "Listo, lo he dejado en Documentos, carpeta Teto."
DOCUMENT_FAILED_REPLY = "Lo he escrito, pero no he podido guardarlo."
DOCUMENT_MAX_TOKENS = 800
MESSAGE_READY_REPLY = "Chat con {name} abierto y mensaje copiado. Pégalo con Control V y envíalo tú:\n\n{message}"
MESSAGE_COPIED_REPLY = "Te lo he copiado, pero no pude abrir el chat. {reason}\n\n{message}"

log = logging.getLogger(__name__)


def _document_request(document: Command) -> str:
    if document.kind == CHAT_MESSAGE:
        return MESSAGE_PROMPT.format(name=document.target) + document.detail
    return DOCUMENT_PROMPTS[document.folder] + document.target


class _TaskSignals(QObject):
    status = Signal(str)
    state = Signal(PetState)
    token = Signal(str)
    notice = Signal(str)
    finished = Signal(str)
    failed = Signal(str)


class _ActionSignals(QObject):
    prepared = Signal(object)
    finished = Signal(str, str)


class _ActionTask(QRunnable):
    """Buscar un archivo o lanzar un programa puede tardar: no debe congelar la interfaz."""

    def __init__(self, tools: ToolRegistry, command: Command, ask_first: bool) -> None:
        super().__init__()
        self.signals = _ActionSignals()
        self._tools = tools
        self._command = command
        self._ask_first = ask_first

    def run(self) -> None:
        command = self._command
        try:
            action = self._tools.prepare(command)
            if self._ask_first:
                self.signals.prepared.emit(action)
                return
            reply, result = self._tools.run(action), "hecho"
        except ActionRejected as exc:
            reply, result = str(exc), "rechazado"
        except OSError as exc:
            log.error("La acción falló: %s", exc)
            reply, result = ACTION_FAILED_REPLY, "error"
        self._tools.record(command.kind, command.target, result)
        self.signals.finished.emit(reply, result)


class _GenerationTask(QRunnable):
    def __init__(
        self,
        resources: ResourceManager,
        compose: Callable[[WebResult], list[dict[str, str]]],
        params: GenerationParams,
        cancel: threading.Event,
        web_search: Callable[[], WebResult] | None = None,
        extra_notice: str = "",
        vision: bool = False,
        finish: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__()
        self._extra_notice = extra_notice
        self._vision = vision
        self._finish = finish
        self._quiet = finish is not None
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
            self.signals.status.emit("Mirando tu pantalla…" if self._vision else "Despertando a Teto…")
            process = (
                self._resources.ensure_loaded(vision=True)
                if self._vision
                else self._resources.ensure_loaded()
            )
            self.signals.status.emit("Escribiendo…" if self._quiet else "")
            text = self._generate(process.base_url, process.api_key, messages)
            if not text and not self._cancel.is_set():
                self.signals.failed.emit(EMPTY_ANSWER_MESSAGE)
                return
            if text:
                self._announce_sources(web)
                if self._extra_notice:
                    self.signals.notice.emit(self._extra_notice)
                if self._finish is not None and not self._cancel.is_set():
                    self.signals.token.emit(self._finish(text))
            self.signals.finished.emit(text)
        except LLMStartError as exc:
            log.error("La IA no pudo arrancar: %s", exc)
            self.signals.failed.emit(
                VISION_UNAVAILABLE_MESSAGE
                if self._vision
                else "No pude cargar la IA. Revisa los modelos en la carpeta models."
            )
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
            if not self._quiet:
                self.signals.token.emit(text)
        tail = parser.finish()
        if tail:
            parts.append(tail)
            if not self._quiet:
                self.signals.token.emit(tail)
        if client.finish_reason == "length":
            self.signals.notice.emit(TRUNCATED_NOTICE)
        return "".join(parts).strip()


class ConversationService(QObject):
    _message_ready = Signal(str)

    def __init__(
        self,
        bus: EventBus,
        resources: ResourceManager,
        settings: Settings,
        knowledge: KnowledgeBase,
        web: MusicLookup | None = None,
        parent: QObject | None = None,
        memory: MemoryStore | None = None,
        tools: ToolRegistry | None = None,
        capture: Callable[[], str] = capture_screen_url,
    ) -> None:
        super().__init__(parent)
        self._tools = tools
        self._capture = capture
        self._pending_action: Action | None = None
        self._action_deadline = 0.0
        self._action_by_button = False
        self._action_signals: _ActionSignals | None = None
        self._bus = bus
        self._resources = resources
        self._settings = settings
        self._knowledge = knowledge
        self._web = web
        self._memory = memory
        self._turn_proposal: Proposal | None = None
        self._pending_proposal: Proposal | None = None
        self._conversation_id: int | None = None
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
        self._message_ready.connect(self._copy_message)
        bus.user_message.connect(self._on_user_message)
        bus.generation_stop_requested.connect(self._on_stop)
        bus.speech_active.connect(self._on_speech_active)
        bus.web_enabled_requested.connect(self._set_web_enabled)
        bus.memory_answered.connect(self._on_memory_answered)
        bus.history_enabled_requested.connect(self._set_history_enabled)
        bus.memory_suggestions_requested.connect(self._set_suggestions_enabled)
        bus.action_answered.connect(self._on_action_answered)
        bus.tools_enabled_requested.connect(self._set_tools_enabled)
        bus.tools_confirm_requested.connect(self._set_tools_confirm)
        bus.allowed_apps_requested.connect(self._set_allowed_apps)

    @property
    def is_busy(self) -> bool:
        return self._cancel is not None or self._action_signals is not None

    @property
    def tools_enabled(self) -> bool:
        return self._tools is not None and bool(self._settings.get("tools.enabled", False))

    @property
    def web_enabled(self) -> bool:
        return self._web is not None and bool(self._settings.get("web.enabled", False))

    @property
    def history_enabled(self) -> bool:
        return self._memory is not None and bool(self._settings.get("memory.save_history", False))

    @property
    def suggestions_enabled(self) -> bool:
        return self._memory is not None and bool(self._settings.get("memory.suggest", True))

    def _on_user_message(self, text: str) -> None:
        text = text.strip()
        if not text or self.is_busy or self._answered_proposal(text):
            return
        if self._answered_action(text) or self._started_action(text):
            return
        proposal = self._proposal_for(text)
        if proposal is not None and proposal.explicit:
            # Sin pasar por el modelo: tiende a confundir de quién es lo que se le pide recordar.
            self._offer_proposal(proposal)
            self._bus.assistant_token.emit(MEMORY_ASK_REPLY)
            self._bus.assistant_done.emit()
            return
        self._start_turn(text, proposal)

    def _start_turn(
        self,
        text: str,
        proposal: Proposal | None = None,
        image_url: str = "",
        document: Command | None = None,
    ) -> None:
        self._rest_timer.stop()
        self._history.append({"role": "user", "content": text})
        # Se recorta de golpe: quitar un turno cada vez cambiaría el inicio de la conversación
        # y el servidor tendría que reprocesarla entera en todos los turnos siguientes.
        if len(self._history) > MAX_HISTORY_MESSAGES:
            self._history = self._history[-KEPT_HISTORY_MESSAGES:]
        entries = self._relevant_knowledge()
        memories = self._relevant_memories(text)
        self._turn_proposal = proposal
        special = bool(image_url) or document is not None
        self._cancel = threading.Event()
        self._resources.set_busy(True)
        self._bus.pet_state_requested.emit(PetState.THINKING)

        finish = None
        if document is not None:
            is_message = document.kind == CHAT_MESSAGE
            finish = partial(self._deliver_message if is_message else self._save_document, document)
        task = _GenerationTask(
            self._resources,
            partial(self._compose, text, entries, memories, image_url, document),
            replace(self._params, max_tokens=DOCUMENT_MAX_TOKENS) if document else self._params,
            self._cancel,
            None if special else self._web_search_for(text),
            "" if special else self._turn_notice(text),
            bool(image_url),
            finish,
        )
        self._launch(task, self._on_finished, self._on_failed)

    def comment(self, title: str) -> bool:
        """Comentario espontáneo: no entra en la conversación ni guarda nada."""
        if self.is_busy:
            return False
        system = system_prompt_for(self._system_prompt, self.tools_enabled)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": COMMENT_PROMPT.format(title=title)},
        ]
        self._cancel = threading.Event()
        self._resources.set_busy(True)
        task = _GenerationTask(self._resources, lambda _web: messages, self._params, self._cancel)
        self._launch(task, self._on_comment_finished, self._on_comment_failed)
        return True

    def _launch(
        self,
        task: _GenerationTask,
        finished: Callable[[str], None],
        failed: Callable[[str], None],
    ) -> None:
        task.signals.status.connect(self._bus.assistant_status)
        task.signals.state.connect(self._bus.pet_state_requested)
        task.signals.token.connect(self._bus.assistant_token)
        task.signals.notice.connect(self._bus.assistant_notice)
        task.signals.finished.connect(finished)
        task.signals.failed.connect(failed)
        self._task_signals = task.signals
        QThreadPool.globalInstance().start(task)

    def _on_comment_finished(self, _text: str) -> None:
        self._end_turn()
        self._bus.assistant_done.emit()

    def _on_comment_failed(self, message: str) -> None:
        log.warning("Comentario descartado: %s", message)
        self._end_turn()

    def _start_look(self, text: str) -> None:
        """La imagen solo vive en esta petición: ni historial, ni disco, ni Internet."""
        assert self._tools is not None
        if self._tools.game_on_screen():
            self._tools.record(LOOK_AT_SCREEN, "", "rechazado")
            self._reply_directly(SCREEN_GAME_REPLY)
            return
        try:
            image_url = self._capture()
        except CaptureError as exc:
            log.error("Captura fallida: %s", exc)
            self._reply_directly(SCREEN_FAILED_REPLY)
            return
        self._tools.record(LOOK_AT_SCREEN, "", "hecho")
        self._start_turn(text, image_url=image_url)

    def _save_document(self, document: Command | None, text: str) -> str:
        """Corre en el hilo de la tarea: PowerPoint tarda en cargarse la primera vez."""
        assert self._tools is not None and document is not None
        try:
            path = self._tools.save_document(document.folder, strip_preamble(text))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            log.error("No se pudo crear el documento: %s", exc)
            self._tools.record(WRITE_DOCUMENT, document.folder, "error")
            return DOCUMENT_FAILED_REPLY
        self._tools.record(WRITE_DOCUMENT, path.name, "hecho")
        return DOCUMENT_SAVED_REPLY

    def _start_message(self, text: str, command: Command) -> None:
        """Se comprueba antes de cargar la IA: sin ese contacto no hay nada que redactar."""
        assert self._tools is not None
        try:
            name = self._tools.contact_name(command.target)
        except ActionRejected as exc:
            self._tools.record(CHAT_MESSAGE, command.target, "rechazado")
            self._reply_directly(str(exc))
            return
        self._start_turn(text, document=replace(command, target=name))

    def _deliver_message(self, command: Command | None, text: str) -> str:
        """Corre en el hilo de la tarea. Aquí no se envía nada: enviarlo es cosa del usuario."""
        assert self._tools is not None and command is not None
        message = strip_preamble(text).strip("\"«»“”")
        self._message_ready.emit(message)
        try:
            name = self._tools.open_chat(command.target)
        except (ActionRejected, OSError) as exc:
            log.error("No se pudo abrir el chat: %s", exc)
            self._tools.record(CHAT_MESSAGE, command.target, "error")
            return MESSAGE_COPIED_REPLY.format(reason=exc, message=message)
        self._tools.record(CHAT_MESSAGE, name, "hecho")
        return MESSAGE_READY_REPLY.format(name=name, message=message)

    def _copy_message(self, message: str) -> None:
        QGuiApplication.clipboard().setText(message)

    def _desktop_titles(self, text: str) -> list[str]:
        """Títulos de ventana, solo si los pide y solo para el modelo local."""
        if not self.tools_enabled or self._tools is None or not asks_open_things(text):
            return []
        current = self._tools.foreground().title
        others = [title for title in self._tools.open_windows() if title != current]
        return [title for title in (current, *others) if title]

    def _turn_notice(self, text: str) -> str:
        if self._tools is not None and not self.tools_enabled and parse_command(text) is not None:
            return TOOLS_OFF_NOTICE
        return WEB_OFF_NOTICE if self._search_would_help(text) else ""

    def _reply_directly(self, reply: str) -> None:
        self._bus.assistant_token.emit(reply)
        self._bus.assistant_done.emit()

    def _started_action(self, text: str) -> bool:
        """Solo el mensaje del usuario llega aquí: lo que escribe el modelo nunca se ejecuta."""
        if not self.tools_enabled or self._tools is None:
            return False
        command = parse_command(text)
        if command is None:
            return False
        if command.kind == LOOK_AT_SCREEN:
            self._start_look(text)
            return True
        if command.kind == WRITE_DOCUMENT:
            self._start_turn(text, document=command)
            return True
        if command.kind == CHAT_MESSAGE:
            self._start_message(text, command)
            return True
        ask_first = bool(self._settings.get("tools.confirm", False))
        self._start_action_task(command, ask_first, by_button=False)
        return True

    def _start_action_task(self, command: Command, ask_first: bool, by_button: bool) -> None:
        assert self._tools is not None
        self._action_by_button = by_button
        task = _ActionTask(self._tools, command, ask_first)
        task.signals.prepared.connect(self._on_action_prepared)
        task.signals.finished.connect(self._on_action_finished)
        self._action_signals = task.signals
        QThreadPool.globalInstance().start(task)

    def _on_action_prepared(self, action: Action) -> None:
        self._action_signals = None
        self._set_pending_action(action)
        self._reply_directly(ACTION_CONFIRM_REPLY.format(summary=action.summary))

    def _set_pending_action(self, action: Action | None) -> None:
        self._pending_action = action
        self._action_deadline = time.monotonic() + ACTION_TIMEOUT_SECONDS
        self._bus.action_proposed.emit(action.summary if action else "")

    def _cancel_pending_action(self) -> None:
        action = self._pending_action
        if action is not None and self._tools is not None:
            self._tools.record(action.command.kind, action.command.target, "cancelado")
        self._set_pending_action(None)

    def _answered_action(self, text: str) -> bool:
        if self._pending_action is None:
            return False
        answer = read_answer(text)
        if answer is None:
            self._cancel_pending_action()
            return False
        self._resolve_action(answer, by_button=False)
        return True

    def _on_action_answered(self, accepted: bool) -> None:
        if self._pending_action is not None and not self.is_busy:
            self._resolve_action(accepted, by_button=True)

    def _resolve_action(self, accepted: bool, by_button: bool) -> None:
        action = self._pending_action
        expired = time.monotonic() > self._action_deadline
        if action is None or not accepted or expired or self._tools is None:
            self._cancel_pending_action()
            reply = ACTION_EXPIRED_REPLY if accepted and expired else ACTION_CANCELLED_REPLY
            self._finish_action(reply, by_button)
            return
        self._set_pending_action(None)
        self._start_action_task(action.command, ask_first=False, by_button=by_button)

    def _on_action_finished(self, reply: str, _result: str) -> None:
        self._action_signals = None
        self._finish_action(reply, self._action_by_button)

    def _finish_action(self, reply: str, by_button: bool) -> None:
        if by_button:
            self._bus.assistant_notice.emit(f"({reply})\n\n")
        else:
            self._reply_directly(reply)

    def _set_tools_enabled(self, enabled: bool) -> None:
        self._settings.set("tools.enabled", enabled)
        if not enabled:
            self._cancel_pending_action()

    def _set_tools_confirm(self, enabled: bool) -> None:
        self._settings.set("tools.confirm", enabled)
        if not enabled:
            self._cancel_pending_action()

    def _set_allowed_apps(self, apps: dict[str, str]) -> None:
        self._settings.set("tools.apps", apps)

    def _relevant_memories(self, text: str) -> list[str]:
        """Los recuerdos solo van al modelo local: nunca entran en una consulta web."""
        if self._memory is None:
            return []
        limit = int(self._settings.get("memory.max_results", 3))
        try:
            found = (
                self._memory.recent(RECENT_MEMORIES)
                if asks_memories(text)
                else self._memory.search(text, limit)
            )
        except MemoryStoreError as exc:
            log.error("Memoria no disponible: %s", exc)
            return []
        return [memory.content for memory in found]

    def _proposal_for(self, text: str) -> Proposal | None:
        if self._memory is None:
            return None
        proposal = detect_proposal(text)
        if proposal is None or not (proposal.explicit or self.suggestions_enabled):
            return None
        try:
            return None if self._memory.contains(proposal.content) else proposal
        except MemoryStoreError as exc:
            log.error("Memoria no disponible: %s", exc)
            return None

    def _offer_proposal(self, proposal: Proposal | None) -> None:
        self._pending_proposal = proposal
        self._bus.memory_proposed.emit(proposal.content if proposal else "")

    def _answered_proposal(self, text: str) -> bool:
        """Un "sí" o un "no" sueltos responden a la propuesta sin pasar por el modelo."""
        if self._pending_proposal is None:
            return False
        answer = read_answer(text)
        if answer is None:
            self._offer_proposal(None)
            return False
        reply = self._resolve_proposal(answer)
        self._bus.assistant_token.emit(reply)
        self._bus.assistant_done.emit()
        return True

    def _on_memory_answered(self, accepted: bool) -> None:
        if self._pending_proposal is not None:
            self._bus.assistant_notice.emit(f"({self._resolve_proposal(accepted)})\n\n")

    def _resolve_proposal(self, accepted: bool) -> str:
        proposal = self._pending_proposal
        self._offer_proposal(None)
        if not accepted or proposal is None or self._memory is None:
            return MEMORY_DECLINED_REPLY
        try:
            self._memory.add(proposal.kind, proposal.content)
        except MemoryStoreError as exc:
            log.error("No se pudo guardar el recuerdo: %s", exc)
            return MEMORY_FAILED_REPLY
        return MEMORY_SAVED_REPLY

    def _save_exchange(self, answer: str) -> None:
        """El historial es opcional: guardar conversaciones enteras exige activarlo antes."""
        if not self.history_enabled or self._memory is None:
            return
        question = next(m["content"] for m in reversed(self._history) if m["role"] == "user")
        try:
            if self._conversation_id is None:
                self._conversation_id = self._memory.start_conversation()
            for role, content in (("user", question), ("assistant", answer)):
                safe = OMITTED_MESSAGE if has_secret(content) else content
                self._memory.add_message(self._conversation_id, role, safe)
        except MemoryStoreError as exc:
            log.error("No se pudo guardar el historial: %s", exc)

    def _set_history_enabled(self, enabled: bool) -> None:
        self._settings.set("memory.save_history", enabled)
        self._conversation_id = None

    def _set_suggestions_enabled(self, enabled: bool) -> None:
        self._settings.set("memory.suggest", enabled)

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
        self,
        text: str,
        entries: list[Entry],
        memories: list[str],
        image_url: str,
        document: Command | None,
        web: WebResult,
    ) -> list[dict[str, Any]]:
        """Corre en el hilo de la tarea: el historial no cambia mientras el turno está activo."""
        self._last_web = web
        if document is not None:
            facts = knowledge_block(entries, False)
            prompt = facts + _document_request(document)
            return [
                {"role": "system", "content": DOCUMENT_SYSTEM},
                {"role": "user", "content": prompt},
            ]
        query = parse_query(text)
        if web.sources and query is not None and not self._knows_topic(query.topic):
            entries = []
        desktop = self._desktop_titles(text)
        block = knowledge_block(entries, wants_opinion(text), web.facts, memories, desktop)
        if web.sources and asks_to_search(text):
            block += SEARCH_DONE
        if image_url:
            block = SCREEN_PROMPT + block
        messages: list[dict[str, Any]] = list(
            build_messages(
                system_prompt_for(self._system_prompt, self.tools_enabled),
                self._history,
                self._context_size,
                self._params.max_tokens,
                block,
            )
        )
        if image_url:
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": messages[-1]["content"]},
                ],
            }
        return messages

    def _set_web_enabled(self, enabled: bool) -> None:
        self._settings.set("web.enabled", enabled)
        self._last_web = WebResult()

    def _on_stop(self) -> None:
        if self._pending_action is not None:
            self._cancel_pending_action()
        if self._cancel is not None:
            self._cancel.set()

    def _on_finished(self, text: str) -> None:
        proposal, self._turn_proposal = self._turn_proposal, None
        if text:
            self._save_exchange(text)
            self._history.append({"role": "assistant", "content": text})
        else:
            self._history.pop()
        self._end_turn()
        self._bus.assistant_done.emit()
        if text and proposal is not None:
            self._offer_proposal(proposal)

    def _on_failed(self, message: str) -> None:
        self._turn_proposal = None
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
