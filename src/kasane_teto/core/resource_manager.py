"""Decide cómo cargar la IA y la descarga tras un tiempo de inactividad."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from kasane_teto.ai.llm_process import LLMConfig, LLMProcess, LLMStartError
from kasane_teto.core.settings import Settings

NVIDIA_SMI_TIMEOUT_SECONDS = 5
MIB = 1024 * 1024

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiProfile:
    name: str
    model_file: str
    gpu_layers: int


def free_vram_mib() -> int | None:
    """VRAM dedicada libre; None si no hay NVIDIA o no se puede consultar."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT_SECONDS,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return int(result.stdout.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        log.warning("No se pudo consultar la VRAM libre")
        return None


def choose_profiles(
    device: str,
    gpu: AiProfile,
    cpu: AiProfile,
    free_mib: int | None,
    required_mib: int,
) -> list[AiProfile]:
    """Perfiles en orden de preferencia; el siguiente se usa si el anterior no arranca."""
    if device == "cpu":
        return [cpu]
    if device == "gpu":
        return [gpu, cpu]
    if free_mib is not None and free_mib >= required_mib:
        return [gpu, cpu]
    return [cpu]


class ResourceManager(QObject):
    unloaded = Signal()

    def __init__(
        self, settings: Settings, models_dir: Path, log_path: Path, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._models_dir = models_dir
        self._log_path = log_path
        self._process: LLMProcess | None = None
        self._lock = threading.Lock()
        self._busy = False

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(int(settings.get("ai.idle_minutes", 5) * 60_000))
        self._idle_timer.timeout.connect(self._on_idle)

    def _profiles(self) -> list[AiProfile]:
        get = self._settings.get
        gpu = AiProfile("gpu", get("ai.gpu_model"), int(get("ai.gpu_layers", 99)))
        cpu = AiProfile("cpu", get("ai.cpu_model"), 0)
        device = str(get("ai.device", "auto"))
        required = int(get("ai.gpu_min_free_mib", 3300))
        free = None if device == "cpu" else free_vram_mib()
        log.info("VRAM libre: %s MiB; dispositivo: %s", free, device)
        return choose_profiles(device, gpu, cpu, free, required)

    def _config(self, profile: AiProfile) -> LLMConfig:
        get = self._settings.get
        return LLMConfig(
            server_path=self._models_dir / "llama" / "llama-server.exe",
            model_path=self._models_dir / "gguf" / profile.model_file,
            context_size=int(get("ai.context_size", 4096)),
            gpu_layers=profile.gpu_layers,
            threads=int(get("ai.threads", 6)),
            load_timeout_seconds=float(get("ai.load_timeout_seconds", 120)),
        )

    def set_busy(self, busy: bool) -> None:
        """Debe llamarse desde el hilo de la UI: controla el temporizador."""
        self._busy = busy
        if busy:
            self._idle_timer.stop()
        else:
            self._idle_timer.start()

    def ensure_loaded(self) -> LLMProcess:
        """Bloquea hasta que la IA esté lista; llamar solo desde un hilo de trabajo."""
        with self._lock:
            if self._process is not None and self._process.is_running:
                return self._process
            last_error: LLMStartError | None = None
            for profile in self._profiles():
                process = LLMProcess(self._config(profile), self._log_path)
                try:
                    process.start()
                except LLMStartError as exc:
                    log.warning("Perfil %s no disponible: %s", profile.name, exc)
                    last_error = exc
                    continue
                log.info("IA cargada con el perfil %s", profile.name)
                self._process = process
                return process
            raise last_error or LLMStartError("No hay ningún perfil de IA disponible")

    def request_unload(self) -> None:
        """Cierra la IA en segundo plano si no está generando."""
        if self._busy:
            return
        self._idle_timer.stop()
        QThreadPool.globalInstance().start(self._unload)

    def _on_idle(self) -> None:
        log.info("Inactividad: se descarga la IA")
        self.request_unload()

    def _unload(self) -> None:
        with self._lock:
            if self._process is None:
                return
            self._process.stop()
            self._process = None
        self.unloaded.emit()

    def shutdown(self) -> None:
        self._idle_timer.stop()
        self._unload()
