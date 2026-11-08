"""Empaqueta la app con PyInstaller en dist\\KasaneTetoAI\\KasaneTetoAI.exe (--onedir).

Uso: .venv\\Scripts\\python.exe scripts\\empaquetar.py

Los modelos, llama.cpp y los entornos de voz no entran en el ejecutable: la app los busca en la
carpeta `models` del proyecto, dos niveles por encima del .exe. Los personajes y las fichas también
se leen de la carpeta del proyecto si existe, para no tener que empaquetar de nuevo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
NAME = "KasaneTetoAI"


def data(source: Path, target: str) -> str:
    return f"{source}{';'}{target}"


def main() -> int:
    package = ROOT / "src" / "kasane_teto"
    PyInstaller.__main__.run([
        str(ROOT / "ejecutar.pyw"),
        "--name", NAME,
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT / "src"),
        "--add-data", data(ROOT / "config", "config"),
        "--add-data", data(ROOT / "workers", "workers"),
        "--add-data", data(ROOT / "assets" / "knowledge", "assets/knowledge"),
        "--add-data", data(ROOT / "assets" / "character" / "provisional", "assets/character/provisional"),
        "--add-data", data(package / "personality" / "prompts", "kasane_teto/personality/prompts"),
        "--collect-data", "pptx",
        "--collect-data", "live2d",  # sombreadores que live2d-py carga desde su carpeta
        "--exclude-module", "pytest",
        "--exclude-module", "PyInstaller",
    ])
    print(f"Listo: {ROOT / 'dist' / NAME / (NAME + '.exe')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
