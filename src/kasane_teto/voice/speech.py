"""Convierte la respuesta en voz por frases, sin bloquear la interfaz."""

from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from kasane_teto.core.events import EventBus
from kasane_teto.core.settings import Settings
from kasane_teto.voice.worker_process import VoiceError

_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'»)]*\s+|\n+")
_UNSPOKEN = re.compile(r"[*_#`~\[\]<>|]")
JOIN_TIMEOUT_SECONDS = 3

log = logging.getLogger(__name__)


def clean_for_speech(text: str) -> str:
    cleaned = " ".join(_UNSPOKEN.sub("", text).split())
    return cleaned if any(c.isalnum() for c in cleaned) else ""


class SentenceSplitter:
    """Agrupa los fragmentos del modelo en frases completas."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        parts = _SENTENCE_END.split(self._buffer)
        self._buffer = parts.pop()
        return [text for text in map(clean_for_speech, parts) if text]

    def flush(self) -> list[str]:
        text = clean_for_speech(self._buffer)
        self._buffer = ""
        return [text] if text else []


class Synthesizer(Protocol):
    sample_rate: int

    def synthesize(self, text: str, length_scale: float): ...
    def unload(self) -> None: ...


class Player(Protocol):
    def play(self, pcm: bytes, rate: int, volume: int, cancel: threading.Event) -> None: ...
    def close(self) -> None: ...


_END_OF_ANSWER = object()
_UNLOAD = object()
_QUIT = object()


class SpeechService(QObject):
    _idle = Signal(bool)

    def __init__(
        self,
        bus: EventBus,
        settings: Settings,
        engine: Synthesizer,
        player: Player,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._settings = settings
        self._engine = engine
        self._player = player
        self._splitter = SentenceSplitter()
        self._queue: queue.Queue[tuple[int, object]] = queue.Queue()
        self._epoch = 0
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(int(settings.get("voice.idle_minutes", 5) * 60_000))
        self._idle_timer.timeout.connect(lambda: self._queue.put((0, _UNLOAD)))
        self._idle.connect(self._on_active_changed)

        bus.assistant_token.connect(self._on_token)
        bus.assistant_done.connect(self._on_done)
        bus.assistant_error.connect(lambda _message: self.stop())
        bus.user_message.connect(lambda _text: self.stop())
        bus.generation_stop_requested.connect(self.stop)
        bus.speech_stop_requested.connect(self.stop)
        bus.tts_enabled_requested.connect(self._set_enabled)

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("voice.tts_enabled", True))

    def set_engine(self, engine: Synthesizer) -> None:
        """Cambia de voz: la anterior se cierra y la nueva carga en la siguiente frase."""
        self.stop()
        self._ensure_thread()
        self._queue.put((0, engine))

    def _set_enabled(self, enabled: bool) -> None:
        self._settings.set("voice.tts_enabled", enabled)
        if not enabled:
            self.stop()
            self._queue.put((0, _UNLOAD))

    def _on_token(self, text: str) -> None:
        if self.enabled:
            self._enqueue(self._splitter.feed(text))

    def _on_done(self) -> None:
        if self.enabled:
            self._enqueue(self._splitter.flush())
            self._queue.put((self._epoch, _END_OF_ANSWER))

    def _ensure_thread(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="voz", daemon=True)
            self._thread.start()

    def _enqueue(self, sentences: list[str]) -> None:
        if sentences:
            self._ensure_thread()
        for sentence in sentences:
            self._queue.put((self._epoch, sentence))

    def stop(self) -> None:
        """Corta lo que esté sonando; lo pendiente de turnos anteriores se descarta."""
        self._epoch += 1
        self._cancel.set()
        self._splitter = SentenceSplitter()
        if self._active:
            self._on_active_changed(False)

    def shutdown(self) -> None:
        self.stop()
        self._idle_timer.stop()
        if self._thread is not None:
            self._queue.put((0, _QUIT))
            self._thread.join(JOIN_TIMEOUT_SECONDS)
            self._thread = None
        self._engine.unload()

    def _on_active_changed(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._bus.speech_active.emit(active)
        if active:
            self._idle_timer.stop()
        else:
            self._idle_timer.start()

    def _run(self) -> None:
        while True:
            epoch, item = self._queue.get()
            if item is _QUIT:
                self._player.close()
                return
            if item is _UNLOAD:
                self._player.close()
                self._engine.unload()
            elif epoch == 0 and not isinstance(item, str) and item is not _END_OF_ANSWER:
                self._engine.unload()
                self._engine = item
            elif epoch != self._epoch:
                continue
            elif item is _END_OF_ANSWER:
                self._player.close()
                self._idle.emit(False)
            else:
                self._speak(epoch, str(item))

    def _speak(self, epoch: int, sentence: str) -> None:
        self._cancel.clear()
        if epoch != self._epoch:
            return
        self._idle.emit(True)
        try:
            length = float(self._settings.get("voice.length_scale", 1.0))
            volume = int(self._settings.get("voice.volume", 80))
            for pcm in self._engine.synthesize(sentence, length):
                if epoch != self._epoch or self._cancel.is_set():
                    # Se agota el generador para dejar el protocolo del proceso sincronizado.
                    continue
                self._player.play(pcm, self._engine.sample_rate, volume, self._cancel)
        except VoiceError as exc:
            log.error("Voz no disponible: %s", exc)
            self._idle.emit(False)
