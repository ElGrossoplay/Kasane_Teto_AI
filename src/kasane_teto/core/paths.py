"""Rutas de recursos de la app y de datos del usuario."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "KasaneTetoAI"
# Los modelos pesan varios GB y nunca van dentro del ejecutable: se buscan junto a él o encima.
MODEL_SEARCH_LEVELS = 3


def is_frozen() -> bool:
    """True si corre como ejecutable de PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """En desarrollo, la carpeta del repositorio; empaquetada, la carpeta interna de recursos."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[3]


def default_config_path() -> Path:
    return project_root() / "config" / "default.toml"


def _beside_executable(name: str) -> Path | None:
    """Carpeta junto al ejecutable o en las de encima, como la del proyecto."""
    here = Path(sys.executable).resolve().parent
    for folder in (here, *here.parents)[:MODEL_SEARCH_LEVELS]:
        if (folder / name).is_dir():
            return folder / name
    return None


def _assets() -> Path:
    """Empaquetada usa los de la carpeta del proyecto si existen: así un personaje nuevo no
    obliga a volver a empaquetar."""
    if is_frozen():
        outside = _beside_executable("assets")
        if outside is not None:
            return outside
    return project_root() / "assets"


def character_root() -> Path:
    return _assets() / "character"


def knowledge_root() -> Path:
    return _assets() / "knowledge"


def workers_dir() -> Path:
    return project_root() / "workers"


def models_dir() -> Path:
    if not is_frozen():
        return project_root() / "models"
    return _beside_executable("models") or Path(sys.executable).resolve().parent / "models"


def data_dir() -> Path:
    """Carpeta de datos del usuario; KASANE_TETO_DATA la sustituye en pruebas."""
    override = os.environ.get("KASANE_TETO_DATA")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA")
        path = Path(base) / APP_DIR_NAME if base else Path.home() / f".{APP_DIR_NAME}"
    path.mkdir(parents=True, exist_ok=True)
    return path
