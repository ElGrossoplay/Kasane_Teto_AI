"""Ciclo de vida de llama-server: una sola instancia, solo en 127.0.0.1."""

from __future__ import annotations

import logging
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import psutil

from kasane_teto.ai.windows_job import KillOnCloseJob

HEALTH_POLL_SECONDS = 0.25
STOP_TIMEOUT_SECONDS = 15

log = logging.getLogger(__name__)


class LLMStartError(Exception):
    """llama-server no pudo arrancar."""


@dataclass(frozen=True)
class LLMConfig:
    server_path: Path
    model_path: Path
    context_size: int
    gpu_layers: int
    threads: int
    load_timeout_seconds: float


def kill_orphans(server_path: Path) -> int:
    """Cierra servidores de esta instalación que hayan quedado de otra ejecución."""
    killed = 0
    target = str(server_path.resolve()).casefold()
    for process in psutil.process_iter(["name", "exe"]):
        exe = process.info["exe"]
        if not exe or exe.casefold() != target:
            continue
        try:
            process.kill()
            killed += 1
        except psutil.Error:
            log.warning("No se pudo cerrar el proceso huérfano %s", process.pid)
    return killed


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LLMProcess:
    def __init__(self, config: LLMConfig, log_path: Path) -> None:
        self._config = config
        self._log_path = log_path
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._job: KillOnCloseJob | None = None
        self.port = 0
        self.api_key = ""

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def build_args(self, port: int, api_key: str) -> list[str]:
        config = self._config
        return [
            str(config.server_path),
            "-m", str(config.model_path),
            "--host", "127.0.0.1",
            "--port", str(port),
            "--api-key", api_key,
            "-c", str(config.context_size),
            "-ngl", str(config.gpu_layers),
            "-t", str(config.threads),
            "-np", "1",
            "--no-mmproj",
            "--no-webui",
            # Sin mapear el archivo: con el modelo en GPU baja la RAM de ~3,2 GB a ~1,1 GB.
            "--load-mode", "none",
        ]

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            config = self._config
            if not config.server_path.is_file():
                raise LLMStartError(f"No se encuentra {config.server_path.name}")
            if not config.model_path.is_file():
                raise LLMStartError(f"No se encuentra el modelo {config.model_path.name}")
            orphans = kill_orphans(config.server_path)
            if orphans:
                log.warning("Cerrados %d servidores huérfanos", orphans)

            self.port = _free_port()
            self.api_key = secrets.token_urlsafe(32)
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("wb") as log_file:
                try:
                    self._process = subprocess.Popen(
                        self.build_args(self.port, self.api_key),
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except OSError as exc:
                    raise LLMStartError(f"No se pudo iniciar la IA: {exc}") from exc
            self._attach_to_job()
            try:
                self._wait_ready()
            except LLMStartError:
                self._terminate()
                raise
            log.info("llama-server listo en el puerto %d", self.port)

    def stop(self) -> None:
        with self._lock:
            self._terminate()

    def _attach_to_job(self) -> None:
        assert self._process is not None
        try:
            if self._job is None:
                self._job = KillOnCloseJob()
            self._job.assign(int(self._process._handle))
        except OSError:
            log.exception("No se pudo crear el Job Object; se limpiará al iniciar")

    def _wait_ready(self) -> None:
        assert self._process is not None
        deadline = time.monotonic() + self._config.load_timeout_seconds
        with httpx.Client(base_url=self.base_url, timeout=2) as client:
            while time.monotonic() < deadline:
                code = self._process.poll()
                if code is not None:
                    raise LLMStartError(f"llama-server terminó con código {code}")
                try:
                    if client.get("/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(HEALTH_POLL_SECONDS)
        raise LLMStartError("El modelo tardó demasiado en cargar")

    def _terminate(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            log.error("llama-server no se cerró a tiempo")
            process.kill()
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        log.info("llama-server cerrado")
