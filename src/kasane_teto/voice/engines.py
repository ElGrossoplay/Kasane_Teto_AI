"""Motores de voz: Piper y faster-whisper, cada uno en su proceso y entorno."""

from __future__ import annotations

import json
import logging
import struct
import threading
from collections.abc import Iterator
from pathlib import Path

from kasane_teto.ai.windows_job import KillOnCloseJob
from kasane_teto.voice.audio import Recording
from kasane_teto.voice.worker_process import VoiceError, WorkerProcess

_LENGTH = struct.Struct("<I")
_AUDIO_HEADER = struct.Struct("<III")

log = logging.getLogger(__name__)
_job_lock = threading.Lock()
_job: KillOnCloseJob | None = None


def _shared_job() -> KillOnCloseJob | None:
    global _job
    with _job_lock:
        if _job is None:
            try:
                _job = KillOnCloseJob()
            except OSError:
                log.exception("No se pudo crear el Job Object de voz")
        return _job


def _venv_python(models: Path, name: str) -> Path:
    return models / name / "venv" / "Scripts" / "python.exe"


class TTSEngine:
    def __init__(self, models: Path, workers: Path, voice: str) -> None:
        self._python = _venv_python(models, "piper")
        self._worker = workers / "piper_worker.py"
        self._model = models / "piper" / "voices" / f"{voice}.onnx"
        self._process: WorkerProcess | None = None
        self.sample_rate = 22050

    def load(self) -> None:
        if self._process is not None and self._process.is_running:
            return
        for path in (self._python, self._worker, self._model):
            if not path.is_file():
                raise VoiceError(f"Falta {path.name}")
        process = WorkerProcess(
            [str(self._python), str(self._worker), str(self._model)], _shared_job()
        )
        self.sample_rate = int(process.start()["sample_rate"])
        self._process = process

    def synthesize(self, text: str, length_scale: float) -> Iterator[bytes]:
        self.load()
        assert self._process is not None
        request = json.dumps({"text": text, "length_scale": length_scale}) + "\n"
        try:
            self._process.stdin.write(request.encode("utf-8"))
            self._process.stdin.flush()
            while True:
                header = self._process.stdout.read(_LENGTH.size)
                if len(header) != _LENGTH.size:
                    raise VoiceError("El proceso de voz se cerró")
                size = _LENGTH.unpack(header)[0]
                if size == 0:
                    return
                yield self._process.stdout.read(size)
        except OSError as exc:
            raise VoiceError(f"Fallo al sintetizar: {exc}") from exc

    def unload(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None


class STTEngine:
    def __init__(
        self, models: Path, workers: Path, threads: int, vocabulary: str, model: str = "small"
    ) -> None:
        self._python = _venv_python(models, "whisper")
        self._worker = workers / "whisper_worker.py"
        self._model = models / "whisper" / model
        self._threads = threads
        self._vocabulary = vocabulary
        self._process: WorkerProcess | None = None

    def load(self) -> None:
        if self._process is not None and self._process.is_running:
            return
        for path in (self._python, self._worker, self._model / "model.bin"):
            if not path.is_file():
                raise VoiceError(f"Falta {path.name}")
        process = WorkerProcess(
            [
                str(self._python),
                str(self._worker),
                str(self._model),
                str(self._threads),
                self._vocabulary,
            ],
            _shared_job(),
        )
        process.start()
        self._process = process

    def transcribe(self, recording: Recording) -> str:
        self.load()
        assert self._process is not None
        header = _AUDIO_HEADER.pack(len(recording.pcm), recording.rate, recording.channels)
        try:
            self._process.stdin.write(header + recording.pcm)
            self._process.stdin.flush()
            line = self._process.stdout.readline()
        except OSError as exc:
            raise VoiceError(f"Fallo al transcribir: {exc}") from exc
        if not line:
            raise VoiceError("El proceso de reconocimiento se cerró")
        return str(json.loads(line)["text"]).strip()

    def unload(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None
