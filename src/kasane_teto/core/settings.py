"""Configuración: valores por defecto en TOML y cambios del usuario en JSON."""

from __future__ import annotations

import json
import logging
import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings:
    def __init__(self, default_path: Path, user_path: Path) -> None:
        self._user_path = user_path
        with default_path.open("rb") as file:
            self._defaults: dict[str, Any] = tomllib.load(file)
        self._user = self._load_user()

    def _load_user(self) -> dict[str, Any]:
        if not self._user_path.exists():
            return {}
        try:
            data = json.loads(self._user_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("Configuración de usuario ilegible; se usan los valores por defecto")
            return {}
        if not isinstance(data, dict):
            log.error("Configuración de usuario con formato inválido; se ignora")
            return {}
        return data

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = _merge(self._defaults, self._user)
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self._user
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
        self._save()

    def _save(self) -> None:
        temp_path = self._user_path.with_suffix(".tmp")
        try:
            temp_path.write_text(json.dumps(self._user, indent=2), encoding="utf-8")
            os.replace(temp_path, self._user_path)
        except OSError:
            log.exception("No se pudo guardar la configuración")
