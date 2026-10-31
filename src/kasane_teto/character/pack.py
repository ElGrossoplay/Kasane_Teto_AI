"""Paquetes de personaje: assets/character/<nombre>/manifest.toml + PNG."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kasane_teto.character.states import PetState

MANIFEST_NAME = "manifest.toml"
MIN_FPS = 0.1
MAX_FPS = 30.0

log = logging.getLogger(__name__)


class PackError(Exception):
    """El paquete de personaje no es válido."""


@dataclass(frozen=True)
class Animation:
    frames: tuple[Path, ...]
    fps: float


@dataclass(frozen=True)
class CharacterPack:
    id: str
    name: str
    author: str
    license: str
    animations: dict[PetState, Animation]

    def animation(self, state: PetState) -> Animation:
        return self.animations.get(state, self.animations[PetState.IDLE])


def list_packs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / MANIFEST_NAME).is_file())


def load_pack(pack_dir: Path) -> CharacterPack:
    manifest_path = pack_dir / MANIFEST_NAME
    try:
        with manifest_path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PackError(f"No se pudo leer {manifest_path}: {exc}") from exc

    states = data.get("states")
    if not isinstance(states, dict):
        raise PackError("El manifiesto no define [states]")

    animations: dict[PetState, Animation] = {}
    for name, spec in states.items():
        try:
            state = PetState(name)
        except ValueError:
            log.warning("Estado desconocido en el paquete %s: %s", pack_dir.name, name)
            continue
        animations[state] = _parse_animation(pack_dir, name, spec)

    if PetState.IDLE not in animations:
        raise PackError("El paquete necesita al menos el estado 'idle'")

    return CharacterPack(
        id=pack_dir.name,
        name=str(data.get("name", pack_dir.name)),
        author=str(data.get("author", "")),
        license=str(data.get("license", "")),
        animations=animations,
    )


def _parse_animation(pack_dir: Path, name: str, spec: Any) -> Animation:
    if not isinstance(spec, dict):
        raise PackError(f"Estado '{name}' inválido")
    frame_names = spec.get("frames")
    if not isinstance(frame_names, list) or not frame_names:
        raise PackError(f"El estado '{name}' no tiene fotogramas")

    fps = spec.get("fps", 2)
    if not isinstance(fps, int | float) or not MIN_FPS <= fps <= MAX_FPS:
        raise PackError(f"fps fuera de rango en el estado '{name}'")

    root = pack_dir.resolve()
    frames: list[Path] = []
    for frame_name in frame_names:
        path = (root / str(frame_name)).resolve()
        if not path.is_relative_to(root):
            raise PackError(f"Fotograma fuera del paquete: {frame_name}")
        if not path.is_file():
            raise PackError(f"Fotograma no encontrado: {frame_name}")
        frames.append(path)
    return Animation(frames=tuple(frames), fps=float(fps))
