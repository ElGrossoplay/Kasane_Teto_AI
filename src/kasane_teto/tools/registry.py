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
from kasane_teto.tools import installed_apps, windows_control
from kasane_teto.tools.commands import (
    CLOSE_APP,
    INFO,
    INFO_BATTERY,
    INFO_CPU,
    INFO_DATE,
    INFO_DISK,
    INFO_MEMORY,
    INFO_TIME,
    MAXIMIZE_APP,
    MINIMIZE_APP,
    OPEN_APP,
    OPEN_FILE,
    OPEN_FOLDER,
    OPEN_URL,
    RESTORE_APP,
    SAFE_FILE_TYPES,
    THIS_WINDOW,
    UNSAFE_FILE_TYPES,
    WEB_SEARCH,
    WINDOW_KINDS,
    Command,
)

BUILTIN_APPS = {"calculadora": "calc.exe", "bloc de notas": "notepad.exe"}
# Permitir estas sería permitir cualquier comando, aunque el usuario las añada al catálogo.
FORBIDDEN_PROGRAMS = frozenset(
    "cmd powershell pwsh wscript cscript mshta regedit regedt32 rundll32 regsvr32 msiexec bash "
    "wsl python pythonw py schtasks sc reg net netsh taskkill bcdedit format diskpart "
    "certutil bitsadmin".split()
)
BROWSER_WORDS = frozenset("navegador browser internet chrome edge firefox brave opera".split())
GENERIC_BROWSER_WORDS = frozenset("navegador browser internet".split())
INSTALLED_APPS_SECONDS = 1800.0
INSTALLED_REFRESH_SECONDS = 60.0
# Las ventanas de navegador se reconocen por el final de su título.
BROWSER_TITLES = ("google chrome", "microsoft edge", "mozilla firefox", "brave", "opera", "vivaldi")
START_PAGE = "https://duckduckgo.com"
KNOWN_SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "twitch": "https://www.twitch.tv",
    "twitter": "https://x.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
    "github": "https://github.com",
    "wikipedia": "https://es.wikipedia.org",
    "vocadb": "https://vocadb.net",
}
# Nombres con los que aparece cada app incluida en su título de ventana.
BUILTIN_TITLES = {
    "calculadora": ("calculadora", "calculator"),
    "bloc de notas": ("bloc de notas", "notepad"),
}
MIN_WINDOW_NAME_CHARS = 3
# Sin confirmación, una orden tan amplia podría cerrar lo que no querías.
VAGUE_WINDOW_NAMES = frozenset("todo todas todos cosas algo ventanas programas aplicaciones".split())
WINDOW_VERBS = {
    CLOSE_APP: ("cerrar", "Cerrada.", "He cerrado"),
    MINIMIZE_APP: ("minimizar", "Minimizada.", "He minimizado"),
    RESTORE_APP: ("restaurar", "Restaurada.", "He restaurado"),
    MAXIMIZE_APP: ("maximizar", "Maximizada.", "He maximizado"),
}
SHOW_MODES = {
    MINIMIZE_APP: windows_control.SW_MINIMIZE,
    RESTORE_APP: windows_control.SW_RESTORE,
    MAXIMIZE_APP: windows_control.SW_MAXIMIZE,
}
MAX_FILES_SCANNED = 5000
MAX_FOLDER_DEPTH = 2
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
    def start_app(self, app_id: str) -> None: ...
    def list_start_apps(self) -> list[tuple[str, str]]: ...
    def open_path(self, path: Path) -> None: ...
    def open_url(self, url: str) -> None: ...
    def list_windows(self) -> list[windows_control.Window]: ...
    def close_window(self, handle: int) -> None: ...
    def show_window(self, handle: int, mode: int) -> None: ...
    def foreground_window(self) -> int: ...


class WindowsRunner:
    list_windows = staticmethod(windows_control.list_windows)
    close_window = staticmethod(windows_control.close_window)
    show_window = staticmethod(windows_control.show_window)
    foreground_window = staticmethod(windows_control.foreground_window)
    list_start_apps = staticmethod(installed_apps.read_start_apps)

    def start_app(self, app_id: str) -> None:
        """Por el Explorador, como un clic en el menú Inicio: la app no es hija de Teto."""
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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
    app_id: str = ""


def validate_program(path: Path) -> None:
    """También se usa al añadir al catálogo: lo que no pase aquí nunca se ejecuta."""
    if path.suffix.casefold() != ".exe":
        raise ActionRejected("Solo puedo abrir programas .exe.")
    if path.stem.casefold() in FORBIDDEN_PROGRAMS or installed_apps.is_blocked_name(path.stem):
        raise ActionRejected(f"{path.name} no se puede usar por seguridad.")
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


def _clean_title(title: str) -> str:
    """Edge esconde un espacio de ancho cero en su nombre."""
    return title.replace("​", "").casefold().strip()


def _is_browser_window(title: str) -> bool:
    return _clean_title(title).endswith(BROWSER_TITLES)


def _has_word(title: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word.casefold())}(?!\w)", _clean_title(title)) is not None


def _file_score(path: Path, wanted: str) -> float:
    """Exacto, todas las palabras pedidas o nombre parecido: la voz rara vez lo dice perfecto."""
    if path.name.casefold() == wanted:
        return 2.0
    key, other = name_key(wanted), name_key(path.stem)
    if key == other:
        return 1.5
    words = set(re.findall(r"\w+", wanted))
    if words and words <= set(re.findall(r"\w+", path.stem.casefold())):
        return 1.2
    return name_similarity(key, other)


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
        self._installed: dict[str, str] = {}
        self._installed_at = float("-inf")

    def _folder(self, name: str) -> Path:
        return self._folders[name] if self._folders is not None else known_folder(name)

    def _all_folders(self) -> list[Path]:
        return [self._folder(name) for name in _FOLDER_LOCATIONS]

    def catalog(self) -> dict[str, str]:
        return {**BUILTIN_APPS, **dict(self._settings.get("tools.apps", {}))}

    def prepare(self, command: Command) -> Action:
        """Valida la orden. Lo que no esté permitido lanza `ActionRejected`."""
        if command.kind == OPEN_APP:
            return self._prepare_open(command)
        if command.kind in WINDOW_KINDS:
            return self._prepare_window(command)
        if command.kind == OPEN_FOLDER:
            path = self._folder(command.target)
            if not path.is_dir():
                raise ActionRejected(f"No encuentro la carpeta de {command.target}.")
            return Action(command, f"Voy a abrir la carpeta de {command.target}", str(path))
        if command.kind == OPEN_FILE:
            path = self._find_file(command.target, command.folder)
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

    def _catalog_name(self, target: str) -> str | None:
        key = name_key(target)
        best_name, best = None, 0.0
        for name in self.catalog():
            score = name_similarity(key, name_key(name))
            if score > best:
                best_name, best = name, score
        return best_name if best >= MIN_NAME_SIMILARITY else None

    def _installed_apps(self, refresh: bool = False) -> dict[str, str]:
        age = time.monotonic() - self._installed_at
        limit = INSTALLED_REFRESH_SECONDS if refresh else INSTALLED_APPS_SECONDS
        if age > limit:
            self._installed = installed_apps.filter_apps(self._runner.list_start_apps())
            self._installed_at = time.monotonic()
        return self._installed

    def _exact_installed(self, target: str, refresh: bool = False) -> str | None:
        key = name_key(target)
        return next((n for n in self._installed_apps(refresh) if name_key(n) == key), None)

    def _containing_installed(self, target: str) -> str | None:
        """"Teams" es "Microsoft Teams"; si hay varias, la de nombre más corto."""
        names = [name for name in self._installed_apps() if _has_word(name, target)]
        return min(names, key=len) if names else None

    def _similar_installed(self, target: str) -> str | None:
        """Lo último: "Teams" se parece a "Steam", y aquí no hay confirmación que lo corrija."""
        key = name_key(target)
        best_name, best = None, 0.0
        for name in self._installed_apps():
            score = name_similarity(key, name_key(name))
            if score > best:
                best_name, best = name, score
        return best_name if best >= MIN_NAME_SIMILARITY else None

    def _prepare_open(self, command: Command) -> Action:
        target = command.target.casefold()
        name = self._catalog_name(target)
        if name is not None:
            found, path = self._find_app(name)
            return Action(command, f"Voy a abrir {found}", str(path))
        if name_key(target) in FORBIDDEN_PROGRAMS or installed_apps.is_blocked_name(target):
            raise ActionRejected(f"{command.target} no lo abro por seguridad.")
        installed = None if target in GENERIC_BROWSER_WORDS else self._exact_installed(target)
        if installed is None and target not in GENERIC_BROWSER_WORDS | set(KNOWN_SITES):
            installed = self._containing_installed(target) or self._similar_installed(target)
        if installed is not None:
            return self._installed_action(command, installed)
        if target in BROWSER_WORDS:
            return Action(Command(OPEN_URL, START_PAGE), "Voy a abrir el navegador", START_PAGE)
        if target in KNOWN_SITES:
            url = KNOWN_SITES[target]
            return Action(Command(OPEN_URL, url), f"Voy a abrir {command.target}", url)
        # Quizá se instaló hace poco: la lista guardada puede estar anticuada.
        installed = self._exact_installed(target, refresh=True)
        if installed is not None:
            return self._installed_action(command, installed)
        raise ActionRejected(f"No encuentro {command.target} entre tus aplicaciones.")

    def _installed_action(self, command: Command, name: str) -> Action:
        return Action(command, f"Voy a abrir {name}", name, self._installed_apps()[name])

    def _prepare_window(self, command: Command) -> Action:
        verb = WINDOW_VERBS[command.kind][0]
        target = command.target.casefold()
        if target == THIS_WINDOW:
            return Action(command, f"Voy a {verb} esta ventana")
        if len(target) < MIN_WINDOW_NAME_CHARS or target in VAGUE_WINDOW_NAMES:
            raise ActionRejected(f"Dime qué ventana quieres {verb}.")
        if target in BROWSER_WORDS or target in KNOWN_SITES:
            return Action(command, f"Voy a {verb} {command.target}")
        name = self._catalog_name(target) or target
        return Action(command, f"Voy a {verb} {name}", name)

    def _windows_for(self, action: Action) -> list[windows_control.Window]:
        target = action.command.target.casefold()
        windows = self._runner.list_windows()
        if target == THIS_WINDOW:
            current = self._runner.foreground_window()
            return [w for w in windows if w.handle == current]
        if target in BROWSER_WORDS:
            return [w for w in windows if _is_browser_window(w.title)]
        if target in KNOWN_SITES:
            return [w for w in windows if _is_browser_window(w.title) and _has_word(w.title, target)]
        words = BUILTIN_TITLES.get(action.resolved, (action.resolved,))
        return [
            w
            for w in windows
            if not _is_browser_window(w.title) and any(_has_word(w.title, word) for word in words)
        ]

    def _act_on_windows(self, action: Action) -> str:
        kind = action.command.kind
        windows = self._windows_for(action)
        if not windows:
            return f"No veo ninguna ventana de {action.command.target}."
        for window in windows:
            if kind == CLOSE_APP:
                self._runner.close_window(window.handle)
            else:
                self._runner.show_window(window.handle, SHOW_MODES[kind])
        _, single, plural = WINDOW_VERBS[kind]
        return single if len(windows) == 1 else f"{plural} {len(windows)} ventanas."

    def _find_app(self, name: str) -> tuple[str, Path]:
        best_name = name
        location = self.catalog()[best_name]
        found = location if Path(location).is_absolute() else shutil.which(location)
        if found is None:
            raise ActionRejected(f"No encuentro {best_name}.")
        path = Path(found)
        validate_program(path)
        return best_name, path

    def _find_file(self, name: str, folder: str = "") -> Path:
        if not name or any(mark in name for mark in '/\\:*?"<>|'):
            raise ActionRejected("Dime solo el nombre del archivo, sin ruta.")
        suffix = Path(name).suffix.casefold()
        if suffix in UNSAFE_FILE_TYPES:
            raise ActionRejected("Solo abro documentos, imágenes y audio.")
        folders = [self._folder(folder)] if folder else self._all_folders()
        scored = [item for place in folders for item in self._matches(place, name.casefold())]
        if not scored:
            raise ActionRejected(f"No encuentro {name} en tus carpetas.")
        best = max(score for score, _ in scored)
        matches = [path for score, path in scored if score == best]
        if len(matches) > 1:
            raise ActionRejected(f"Hay varios archivos que se llaman parecido a {name}.")
        return matches[0]

    @staticmethod
    def _matches(folder: Path, wanted: str) -> list[tuple[float, Path]]:
        """Recorre pocos niveles y sin seguir enlaces: nunca sale de la carpeta conocida."""
        found: list[tuple[float, Path]] = []
        scanned = 0
        for root, folders, files in os.walk(folder):
            if len(Path(root).relative_to(folder).parts) >= MAX_FOLDER_DEPTH:
                folders.clear()
            for file in files:
                scanned += 1
                path = Path(root, file)
                if path.suffix.casefold() not in SAFE_FILE_TYPES or path.is_symlink():
                    continue
                score = _file_score(path, wanted)
                if score >= MIN_NAME_SIMILARITY:
                    found.append((score, path))
            if scanned >= MAX_FILES_SCANNED:
                break
        return found

    def run(self, action: Action) -> str:
        """Vuelve a validar: entre la confirmación y este momento algo pudo cambiar."""
        checked = self.prepare(action.command)
        command = checked.command
        if command.kind in WINDOW_KINDS:
            return self._act_on_windows(checked)
        if checked.app_id:
            self._runner.start_app(checked.app_id)
        elif command.kind == OPEN_APP:
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
