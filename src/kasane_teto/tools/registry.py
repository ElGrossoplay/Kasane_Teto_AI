"""Lista blanca de acciones: valida cada orden, la ejecuta y deja constancia.

Las apps se lanzan sin argumentos y nunca con `shell=True`. La información del equipo solo usa
datos globales: no se listan ni se abren procesos, para no interferir con juegos ni anticheat.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
import webbrowser
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus, urlsplit

import psutil
from PySide6.QtCore import QStandardPaths

from kasane_teto.core.settings import Settings
from kasane_teto.memory.knowledge import MIN_NAME_SIMILARITY, name_key, name_similarity
from kasane_teto.memory.proposals import has_secret
from kasane_teto.tools.commands import (
    INFO,
    INFO_BATTERY,
    INFO_CPU,
    INFO_DATE,
    INFO_DISK,
    INFO_MEMORY,
    INFO_TIME,
    OPEN_APP,
    OPEN_FILE,
    OPEN_FOLDER,
    OPEN_URL,
    SAFE_FILE_TYPES,
    WEB_SEARCH,
    Command,
)

BUILTIN_APPS = {"calculadora": "calc.exe", "bloc de notas": "notepad.exe"}
# Permitir estas sería permitir cualquier comando, aunque el usuario las añada al catálogo.
FORBIDDEN_PROGRAMS = frozenset(
    "cmd powershell pwsh wscript cscript mshta regedit regedt32 rundll32 regsvr32 msiexec bash "
    "wsl python pythonw py schtasks sc reg net netsh taskkill bcdedit format diskpart "
    "certutil bitsadmin".split()
)
SEARCH_URL = "https://duckduckgo.com/?q="
MAX_SEARCH_CHARS = 120
CPU_SAMPLE_SECONDS = 0.3
DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre",
)
INFO_SUMMARIES = {
    INFO_TIME: "Voy a mirar la hora",
    INFO_DATE: "Voy a mirar la fecha",
    INFO_MEMORY: "Voy a mirar el uso de memoria",
    INFO_CPU: "Voy a mirar el uso del procesador",
    INFO_DISK: "Voy a mirar el espacio en disco",
    INFO_BATTERY: "Voy a mirar la batería",
}
_FOLDER_LOCATIONS = {
    "documentos": QStandardPaths.StandardLocation.DocumentsLocation,
    "descargas": QStandardPaths.StandardLocation.DownloadLocation,
    "imagenes": QStandardPaths.StandardLocation.PicturesLocation,
    "musica": QStandardPaths.StandardLocation.MusicLocation,
    "videos": QStandardPaths.StandardLocation.MoviesLocation,
    "escritorio": QStandardPaths.StandardLocation.DesktopLocation,
}
_NUMERIC_HOST = re.compile(r"^[\d.]+$")

log = logging.getLogger(__name__)


class ActionRejected(Exception):
    """La orden no está permitida; el texto se muestra al usuario."""


class SystemRunner(Protocol):
    def start_program(self, path: Path) -> None: ...
    def open_path(self, path: Path) -> None: ...
    def open_url(self, url: str) -> None: ...


class WindowsRunner:
    def start_program(self, path: Path) -> None:
        subprocess.Popen(
            [str(path)],
            cwd=path.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def open_path(self, path: Path) -> None:
        os.startfile(path)  # type: ignore[attr-defined]

    def open_url(self, url: str) -> None:
        if not webbrowser.open(url):
            raise OSError("El navegador no respondió")


@dataclass(frozen=True)
class Action:
    command: Command
    summary: str
    resolved: str = ""


def validate_program(path: Path) -> None:
    """También se usa al añadir al catálogo: lo que no pase aquí nunca se ejecuta."""
    if path.suffix.casefold() != ".exe":
        raise ActionRejected("Solo puedo abrir programas .exe.")
    if path.stem.casefold() in FORBIDDEN_PROGRAMS:
        raise ActionRejected(f"{path.name} no se puede usar: permitiría ejecutar cualquier comando.")
    if not path.is_file():
        raise ActionRejected(f"No encuentro {path.name}.")


def validate_url(url: str) -> str:
    """Solo https con un dominio normal: nada de file:, javascript:, usuarios ni equipos locales."""
    candidate = url if "://" in url else f"https://{url}"
    try:
        parts = urlsplit(candidate)
        host = parts.hostname or ""
        has_port = parts.port is not None
    except ValueError as exc:
        raise ActionRejected("Solo abro enlaces https normales.") from exc
    if parts.scheme != "https" or "@" in parts.netloc or has_port:
        raise ActionRejected("Solo abro enlaces https normales.")
    if "." not in host or host == "localhost" or _NUMERIC_HOST.match(host):
        raise ActionRejected("Solo abro enlaces https normales.")
    return candidate


def known_folder(name: str) -> Path:
    return Path(QStandardPaths.writableLocation(_FOLDER_LOCATIONS[name]))


def _gigabytes(size: float) -> str:
    return f"{size / 1024 ** 3:.1f}".replace(".", ",")


class ToolRegistry:
    def __init__(
        self,
        settings: Settings,
        log_path: Path,
        runner: SystemRunner | None = None,
        folders: Mapping[str, Path] | None = None,
    ) -> None:
        self._settings = settings
        self._log_path = log_path
        self._runner = runner or WindowsRunner()
        self._folders = folders

    def _folder(self, name: str) -> Path:
        return self._folders[name] if self._folders is not None else known_folder(name)

    def _all_folders(self) -> list[Path]:
        return [self._folder(name) for name in _FOLDER_LOCATIONS]

    def catalog(self) -> dict[str, str]:
        return {**BUILTIN_APPS, **dict(self._settings.get("tools.apps", {}))}

    def prepare(self, command: Command) -> Action:
        """Valida la orden. Lo que no esté permitido lanza `ActionRejected`."""
        if command.kind == OPEN_APP:
            name, path = self._find_app(command.target)
            return Action(command, f"Voy a abrir {name}", str(path))
        if command.kind == OPEN_FOLDER:
            path = self._folder(command.target)
            if not path.is_dir():
                raise ActionRejected(f"No encuentro la carpeta de {command.target}.")
            return Action(command, f"Voy a abrir la carpeta de {command.target}", str(path))
        if command.kind == OPEN_FILE:
            path = self._find_file(command.target)
            return Action(command, f"Voy a abrir {path.name}", str(path))
        if command.kind == OPEN_URL:
            url = validate_url(command.target)
            return Action(command, f"Voy a abrir {url} en el navegador", url)
        if command.kind == WEB_SEARCH:
            return self._prepare_search(command)
        if command.kind == INFO:
            return Action(command, INFO_SUMMARIES[command.target])
        raise ActionRejected("Eso no lo puedo hacer.")

    def _prepare_search(self, command: Command) -> Action:
        if has_secret(command.target) or len(command.target) > MAX_SEARCH_CHARS:
            raise ActionRejected("Eso no lo busco: parece un dato sensible o es demasiado largo.")
        url = SEARCH_URL + quote_plus(command.target)
        return Action(command, f"Voy a buscar «{command.target}» en el navegador", url)

    def _find_app(self, target: str) -> tuple[str, Path]:
        key = name_key(target)
        best_name, best = None, 0.0
        for name in self.catalog():
            score = name_similarity(key, name_key(name))
            if score > best:
                best_name, best = name, score
        if best_name is None or best < MIN_NAME_SIMILARITY:
            raise ActionRejected(
                f"{target} no está en mi lista de aplicaciones. Añádelo en Configuración."
            )
        location = self.catalog()[best_name]
        found = location if Path(location).is_absolute() else shutil.which(location)
        if found is None:
            raise ActionRejected(f"No encuentro {best_name}.")
        path = Path(found)
        validate_program(path)
        return best_name, path

    def _find_file(self, name: str) -> Path:
        if not name or any(mark in name for mark in '/\\:*?"<>|'):
            raise ActionRejected("Dime solo el nombre del archivo, sin ruta.")
        suffix = Path(name).suffix.casefold()
        if suffix and suffix not in SAFE_FILE_TYPES:
            raise ActionRejected("Solo abro documentos, imágenes y audio.")
        matches = [path for folder in self._all_folders() for path in self._matches(folder, name)]
        if not matches:
            raise ActionRejected(f"No encuentro {name} en tus carpetas.")
        if len(matches) > 1:
            raise ActionRejected(f"Hay varios archivos llamados {name}: dime la extensión.")
        return matches[0]

    @staticmethod
    def _matches(folder: Path, name: str) -> list[Path]:
        if not folder.is_dir():
            return []
        wanted = name.casefold()
        found = []
        for entry in os.scandir(folder):
            path = Path(entry.path)
            if not entry.is_file(follow_symlinks=False):
                continue
            if path.suffix.casefold() not in SAFE_FILE_TYPES:
                continue
            if path.name.casefold() == wanted or path.stem.casefold() == wanted:
                found.append(path)
        return found

    def run(self, action: Action) -> str:
        """Vuelve a validar: entre la confirmación y este momento algo pudo cambiar."""
        checked = self.prepare(action.command)
        command = checked.command
        if command.kind == OPEN_APP:
            self._runner.start_program(Path(checked.resolved))
        elif command.kind in (OPEN_FOLDER, OPEN_FILE):
            self._runner.open_path(Path(checked.resolved))
        elif command.kind in (OPEN_URL, WEB_SEARCH):
            self._runner.open_url(checked.resolved)
        else:
            return system_info(command.target)
        return "Hecho."

    def record(self, action: str, target: str, result: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp}\t{action}\t{' '.join(target.split())}\t{result}\n"
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as file:
                file.write(line)
        except OSError:
            log.exception("No se pudo escribir el registro de acciones")


def system_info(name: str) -> str:
    now = datetime.now()
    if name == INFO_TIME:
        return f"Son las {now:%H:%M}."
    if name == INFO_DATE:
        return f"Hoy es {DAYS[now.weekday()]} {now.day} de {MONTHS[now.month - 1]} de {now.year}."
    if name == INFO_MEMORY:
        memory = psutil.virtual_memory()
        return (
            f"Estás usando {_gigabytes(memory.used)} GB de {_gigabytes(memory.total)} GB "
            f"de memoria, un {memory.percent:.0f} %."
        )
    if name == INFO_CPU:
        return f"El procesador va al {psutil.cpu_percent(interval=CPU_SAMPLE_SECONDS):.0f} %."
    if name == INFO_DISK:
        return _disk_report()
    if name == INFO_BATTERY:
        return _battery_report()
    raise ActionRejected("Eso no lo puedo consultar.")


def _disk_report() -> str:
    parts = []
    for partition in psutil.disk_partitions(all=False):
        if "fixed" not in partition.opts:
            continue
        usage = psutil.disk_usage(partition.mountpoint)
        letter = partition.mountpoint.rstrip(":\\/")
        parts.append(f"{letter}: {_gigabytes(usage.free)} GB libres")
    return "; ".join(parts) + "." if parts else "No he podido leer los discos."


def _battery_report() -> str:
    battery = psutil.sensors_battery()
    if battery is None:
        return "No detecto ninguna batería."
    plugged = "conectado a la corriente" if battery.power_plugged else "sin cargador"
    return f"La batería está al {battery.percent:.0f} %, {plugged}."
