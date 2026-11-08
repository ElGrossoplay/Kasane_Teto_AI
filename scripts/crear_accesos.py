"""Crea los accesos directos de Teto en el menú Inicio y en el escritorio.

Uso: .venv\\Scripts\\python.exe scripts\\crear_accesos.py [--quitar]

Apuntan al ejecutable de dist\\KasaneTetoAI, o a ejecutar.pyw si aún no se ha empaquetado. Solo
crea o borra esos dos archivos .lnk de tu perfil: no toca el registro ni instala nada.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_NAME = "Kasane Teto AI.lnk"
# Las rutas viajan por variables de entorno: así ninguna comilla de una ruta rompe la orden.
CREATE = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TETO_LINK);"
    "$s.TargetPath = $env:TETO_TARGET; $s.Arguments = $env:TETO_ARGS;"
    "$s.WorkingDirectory = $env:TETO_DIR; $s.Description = 'Kasane Teto AI'; $s.Save()"
)
DESKTOP = "[Environment]::GetFolderPath('Desktop')"


def desktop_dir() -> Path:
    """El escritorio puede estar en OneDrive: lo dice Windows, no se adivina."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", DESKTOP],
        capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return Path(result.stdout.strip())


def target() -> tuple[Path, str, Path]:
    exe = ROOT / "dist" / "KasaneTetoAI" / "KasaneTetoAI.exe"
    if exe.exists():
        return exe, "", exe.parent
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return pythonw, f'"{ROOT / "ejecutar.pyw"}"', ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quitar", action="store_true", help="borra los accesos directos")
    args = parser.parse_args()
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    links = [start_menu / LINK_NAME, desktop_dir() / LINK_NAME]
    if args.quitar:
        for link in links:
            link.unlink(missing_ok=True)
            print(f"Quitado: {link}")
        return 0
    program, arguments, workdir = target()
    for link in links:
        env = {**os.environ, "TETO_LINK": str(link), "TETO_TARGET": str(program),
               "TETO_ARGS": arguments, "TETO_DIR": str(workdir)}
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", CREATE],
            env=env, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"Creado: {link} → {program}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
