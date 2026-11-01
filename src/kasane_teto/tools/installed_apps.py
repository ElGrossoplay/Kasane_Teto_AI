"""Aplicaciones instaladas según el menú Inicio. Consultarlas no abre ningún proceso."""

from __future__ import annotations

import json
import logging
import subprocess

from kasane_teto.memory.knowledge import name_key

LIST_TIMEOUT_SECONDS = 20
_LIST_COMMAND = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
)

# Abrirlas por voz y sin preguntar podría ejecutar cualquier cosa o cambiar el sistema.
BLOCKED_NAMES = (
    "cheatengine", "unloadkernel", "resetsettings", "powershell", "simbolodelsistema", "terminal",
    "gitbash", "gitcmd", "python", "pydoc", "editordelregistro", "regedit", "ejecutar",
    "configuraciondelsistema", "programadordetareas", "administraciondeequipos",
    "herramientasdewindows", "servicios", "firewall", "unidadderecuperacion",
    "diagnosticodememoria", "desfragmentar", "liberadordeespacio", "odbc", "iscsi", "desinstalar",
    "uninstall",
)
BLOCKED_IDS = (
    "cheat engine", "cmd.exe", "powershell", "regedit", "python.exe", "uninstall", "msconfig",
)
# No son aplicaciones: manuales, ayudas y enlaces que Windows lista junto a ellas.
NOISE_NAMES = (
    "ayuda", "help", "manual", "documentation", "tutorial", "faq", "releasenotes", "novedades",
    "troubleshooter",
)
NOISE_ID_ENDINGS = (".chm", ".txt", ".html", ".htm", ".pdf", ".msc", ".url")

log = logging.getLogger(__name__)


def is_blocked_name(name: str) -> bool:
    key = name_key(name)
    return any(blocked in key for blocked in BLOCKED_NAMES)


def _usable(name: str, app_id: str) -> bool:
    key, identifier = name_key(name), app_id.casefold()
    if not key or not identifier or is_blocked_name(name):
        return False
    if any(blocked in identifier for blocked in BLOCKED_IDS):
        return False
    if identifier.startswith(("http:", "https:")) or identifier.endswith(NOISE_ID_ENDINGS):
        return False
    return not any(noise in key for noise in NOISE_NAMES)


def filter_apps(apps: list[tuple[str, str]]) -> dict[str, str]:
    return {name: app_id for name, app_id in apps if _usable(name, app_id)}


def read_start_apps() -> list[tuple[str, str]]:
    """Orden fija y sin consola visible: nada de lo que diga el usuario entra en el comando."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _LIST_COMMAND],
            capture_output=True,
            timeout=LIST_TIMEOUT_SECONDS,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        data = json.loads(result.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.error("No se pudo leer la lista de aplicaciones: %s", exc)
        return []
    items = data if isinstance(data, list) else [data]
    return [(str(item.get("Name", "")).strip(), str(item.get("AppID", ""))) for item in items]
