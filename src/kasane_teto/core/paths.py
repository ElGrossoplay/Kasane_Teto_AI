"""Rutas de recursos de la app y de datos del usuario."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "KasaneTetoAI"


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_config_path() -> Path:
    return project_root() / "config" / "default.toml"


def character_root() -> Path:
    return project_root() / "assets" / "character"


def knowledge_root() -> Path:
    return project_root() / "assets" / "knowledge"


def models_dir() -> Path:
    return project_root() / "models"


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
