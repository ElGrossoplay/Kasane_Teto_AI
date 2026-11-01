"""Detecta código nuevo: sin esto, abrir la app solo enseña la versión que ya estaba corriendo."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

WATCHED_FOLDERS = ("src", "config", "workers")
WATCHED_TYPES = frozenset((".py", ".toml", ".txt"))

log = logging.getLogger(__name__)


def code_changed_since(moment: float, root: Path) -> bool:
    for folder in WATCHED_FOLDERS:
        for path in (root / folder).rglob("*"):
            try:
                if path.suffix in WATCHED_TYPES and path.stat().st_mtime > moment:
                    return True
            except OSError:
                continue
    return False


def relaunch(root: Path) -> None:
    """Sin consola y sin depender de esta app, que está a punto de cerrarse."""
    try:
        subprocess.Popen(
            [sys.executable, str(root / "ejecutar.pyw")],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError:
        log.exception("No se pudo reiniciar la app")
