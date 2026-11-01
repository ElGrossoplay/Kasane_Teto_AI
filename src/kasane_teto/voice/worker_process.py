"""Proceso auxiliar de voz: se comunica por tuberías y muere con la app."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import IO, Any

from kasane_teto.ai.windows_job import KillOnCloseJob

STOP_TIMEOUT_SECONDS = 5

log = logging.getLogger(__name__)


class VoiceError(Exception):
    """Un componente de voz no está disponible."""


class WorkerProcess:
    def __init__(self, args: list[str], job: KillOnCloseJob | None = None) -> None:
        self._args = args
        self._job = job
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def stdin(self) -> IO[bytes]:
        assert self._process is not None and self._process.stdin is not None
        return self._process.stdin

    @property
    def stdout(self) -> IO[bytes]:
        assert self._process is not None and self._process.stdout is not None
        return self._process.stdout

    def start(self) -> dict[str, Any]:
        """Arranca el proceso y espera su línea JSON de listo en stderr."""
        try:
            self._process = subprocess.Popen(
                self._args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise VoiceError(f"No se pudo iniciar el proceso: {exc}") from exc
        assert self._process.stderr is not None
        if self._job is not None:
            try:
                self._job.assign(int(self._process._handle))
            except OSError:
                log.exception("No se pudo asociar el proceso de voz al Job Object")
        ready = self._read_ready(self._process.stderr)
        threading.Thread(target=self._drain, args=(self._process.stderr,), daemon=True).start()
        return ready

    def _read_ready(self, stream: IO[bytes]) -> dict[str, Any]:
        for line in stream:
            try:
                data = json.loads(line)
            except ValueError:
                log.debug("Proceso de voz: %r", line[:200])
                continue
            if isinstance(data, dict):
                return data
        self.stop()
        raise VoiceError("El proceso de voz terminó al arrancar")

    @staticmethod
    def _drain(stream: IO[bytes]) -> None:
        for line in stream:
            log.warning("Proceso de voz: %s", line[:300].decode("utf-8", "replace").rstrip())

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
