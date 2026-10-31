"""Mide RAM, CPU y VRAM de la app y guarda una muestra por segundo en CSV.

Uso: .venv\\Scripts\\python.exe scripts\\medir_recursos.py --segundos 60 --salida medida.csv
Con --pid mide una instancia ya abierta; sin él, abre la app y la cierra al terminar.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def vram_used_mib() -> int | None:
    if shutil.which("nvidia-smi") is None:
        return None
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(result.stdout.strip()) if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--segundos", type=int, default=60)
    parser.add_argument("--espera", type=int, default=5, help="segundos antes de medir")
    parser.add_argument("--salida", type=Path, default=Path("medida.csv"))
    args = parser.parse_args()

    child: subprocess.Popen[bytes] | None = None
    if args.pid is None:
        child = subprocess.Popen([sys.executable, str(ROOT / "ejecutar.pyw")])
        pid = child.pid
    else:
        pid = args.pid

    process = psutil.Process(pid)
    logical_cpus = psutil.cpu_count() or 1
    time.sleep(args.espera)
    # El python.exe de un .venv en Windows es un lanzador: la app real es su hijo.
    children = process.children(recursive=True)
    if children:
        process = max(children, key=lambda p: p.memory_info().rss)
    process.cpu_percent(None)

    ram_samples: list[float] = []
    cpu_samples: list[float] = []
    vram_samples: list[int] = []
    try:
        with args.salida.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["segundo", "ram_mb", "cpu_pct", "vram_total_mib"])
            for second in range(args.segundos):
                time.sleep(1)
                ram = process.memory_info().rss / 1024 / 1024
                cpu = process.cpu_percent(None) / logical_cpus
                vram = vram_used_mib()
                ram_samples.append(ram)
                cpu_samples.append(cpu)
                if vram is not None:
                    vram_samples.append(vram)
                writer.writerow([second, f"{ram:.1f}", f"{cpu:.2f}", vram])
    finally:
        if child is not None:
            child.terminate()
            child.wait(timeout=10)

    print(f"RAM MB   media {statistics.mean(ram_samples):.1f} | max {max(ram_samples):.1f}")
    print(f"CPU %    media {statistics.mean(cpu_samples):.2f} | max {max(cpu_samples):.2f}")
    if vram_samples:
        print(f"VRAM MiB (todo el sistema) min {min(vram_samples)} | max {max(vram_samples)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
