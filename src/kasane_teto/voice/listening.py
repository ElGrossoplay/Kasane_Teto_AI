"""Graba con push-to-talk y convierte la voz en texto en segundo plano."""

from __future__ import annotations

import logging
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from kasane_teto.character.states import PetState
from kasane_teto.core.events import EventBus
from kasane_teto.core.settings import Settings
from kasane_teto.voice.audio import Recording, is_silence
from kasane_teto.voice.worker_process import VoiceError

MAX_RECORDING_MS = 30_000
MIN_RECORDING_SECONDS = 0.3

log = logging.getLogger(__name__)


class Recognizer(Protocol):
    def transcribe(self, recording: Recording) -> str: ...
    def unload(self) -> None: ...


class Recorder(Protocol):
    def start(self) -> None: ...
    def stop(self) -> Recording: ...


class _Signals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, engine: Recognizer, recording: Recording) -> None:
        super().__init__()
        self.signals = _Signals()
        self._engine = engine
        self._recording = recording

    def run(self) -> None:
        try:
            self.signals.finished.emit(self._engine.transcribe(self._recording))
        except VoiceError as exc:
            log.error("Reconocimiento no disponible: %s", exc)
            self.signals.failed.emit("No pude cargar el reconocimiento de voz.")


class ListenService(QObject):
    def __init__(
        self,
        bus: EventBus,
        settings: Settings,
        engine: Recognizer,
        recorder: Recorder,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._settings = settings
        self._engine = engine
        self._recorder = recorder
        self._recording = False
        self._task_signals: _Signals | None = None

        self._limit = QTimer(self)
        self._limit.setSingleShot(True)
        self._limit.setInterval(MAX_RECORDING_MS)
        self._limit.timeout.connect(self.stop_listening)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(int(settings.get("voice.idle_minutes", 5) * 60_000))
        self._idle_timer.timeout.connect(self._unload)

        bus.listen_toggled.connect(self.toggle)
        bus.listen_started.connect(self.start_listening)
        bus.listen_stopped.connect(self.stop_listening)
        bus.mic_enabled_requested.connect(self._set_enabled)

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("voice.mic_enabled", False))

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _set_enabled(self, enabled: bool) -> None:
        self._settings.set("voice.mic_enabled", enabled)
        if not enabled:
            if self._recording:
                self._recording = False
                self._limit.stop()
                self._recorder.stop()
                self._bus.pet_state_requested.emit(PetState.IDLE)
            self._unload()

    def toggle(self) -> None:
        if self._recording:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self) -> None:
        if self._recording or self._task_signals is not None:
            return
        if not self.enabled:
            self._bus.voice_status.emit("El micrófono está apagado: actívalo en Configuración.")
            return
        self._bus.speech_stop_requested.emit()
        try:
            self._recorder.start()
        except VoiceError as exc:
            log.error("Micrófono no disponible: %s", exc)
            self._bus.voice_status.emit("No pude abrir el micrófono.")
            return
        self._recording = True
        self._idle_timer.stop()
        self._limit.start()
        self._bus.pet_state_requested.emit(PetState.LISTENING)
        self._bus.voice_status.emit("Te escucho…")

    def stop_listening(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self._limit.stop()
        recording = self._recorder.stop()
        if recording.seconds < MIN_RECORDING_SECONDS or is_silence(recording.pcm):
            self._finish("No te he oído.")
            return
        self._bus.pet_state_requested.emit(PetState.THINKING)
        self._bus.voice_status.emit("Entendiendo…")
        task = _Task(self._engine, recording)
        task.signals.finished.connect(self._on_transcribed)
        task.signals.failed.connect(self._on_failed)
        self._task_signals = task.signals
        QThreadPool.globalInstance().start(task)

    def _on_transcribed(self, text: str) -> None:
        self._task_signals = None
        if text:
            self._bus.voice_status.emit("")
            self._bus.transcript_ready.emit(text)
            self._idle_timer.start()
        else:
            self._finish("No te he entendido.")

    def _on_failed(self, message: str) -> None:
        self._task_signals = None
        self._finish(message)

    def _finish(self, message: str) -> None:
        self._bus.pet_state_requested.emit(PetState.IDLE)
        self._bus.voice_status.emit(message)
        self._idle_timer.start()

    def _unload(self) -> None:
        self._idle_timer.stop()
        QThreadPool.globalInstance().start(self._engine.unload)

    def shutdown(self) -> None:
        self._limit.stop()
        self._idle_timer.stop()
        if self._recording:
            self._recording = False
            self._recorder.stop()
        self._engine.unload()
