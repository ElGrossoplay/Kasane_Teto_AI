"""Prueba de estabilidad: la app real durante horas, con turnos y cambios de estado periódicos.

Uso: .venv\\Scripts\\python.exe scripts\\prueba_estabilidad.py --horas 8 --salida estabilidad.csv

Usa una carpeta de datos temporal, así que no toca recuerdos ni configuración. La voz suena a
volumen 0 y el micrófono queda apagado. Si hay un juego en primer plano, Teto pasa al modo juego y
la prueba se salta los turnos para no quitarle CPU ni GPU.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psutil  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

MESSAGES = (
    "Hola, ¿qué tal estás?",
    "¿Quién es Hatsune Miku?",
    "Cuéntame algo sobre el pan.",
    "¿Qué hora es?",
    "Dime tres colores.",
    "¿Te gusta la música?",
)
SAMPLE_SECONDS = 60


def vram_free_mib() -> int | None:
    from kasane_teto.core.resource_manager import free_vram_mib

    return free_vram_mib()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horas", type=float, default=8)
    parser.add_argument("--minutos-entre-turnos", type=float, default=7)
    parser.add_argument("--salida", type=Path, default=Path("estabilidad.csv"))
    parser.add_argument("--live2d", type=Path, help="ruta a un .model3.json para probar Live2D")
    args = parser.parse_args()

    data = Path(tempfile.mkdtemp(prefix="teto_estabilidad_"))
    os.environ["KASANE_TETO_DATA"] = str(data)
    settings: dict[str, dict[str, object]] = {"voice": {"volume": 0, "mic_enabled": False}}
    if args.live2d:
        settings["pet"] = {"pack": "live2d", "live2d_model": str(args.live2d), "scale": 50}
    (data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    from kasane_teto.core.activity import Activity
    from kasane_teto.core.logging_setup import setup_logging
    from kasane_teto.core.paths import default_config_path
    from kasane_teto.core.settings import Settings
    from kasane_teto.main import TetoApp

    setup_logging(data)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    teto = TetoApp(app, Settings(default_config_path(), data / "settings.json"), data)
    teto.start()
    me = psutil.Process()
    me.cpu_percent(None)
    logical_cpus = psutil.cpu_count() or 1
    started = time.monotonic()
    counts = {"turnos": 0, "respuestas": 0, "errores": 0, "saltados": 0}
    teto._bus.assistant_done.connect(lambda: counts.__setitem__("respuestas", counts["respuestas"] + 1))
    teto._bus.assistant_error.connect(lambda _m: counts.__setitem__("errores", counts["errores"] + 1))

    out = args.salida.open("w", newline="", encoding="utf-8")
    writer = csv.writer(out)
    writer.writerow(
        ["minuto", "app_mb", "hijos_mb", "hilos", "handles", "cpu_pct", "vram_libre_mib", "estado"]
    )
    samples: list[tuple[float, float, str]] = []

    def sample() -> None:
        minute = (time.monotonic() - started) / 60
        children = me.children(recursive=True)
        kids = sum(c.memory_info().rss for c in children if c.is_running()) / 2**20
        app_mb = me.memory_info().rss / 2**20
        state = teto._activity.state.value
        writer.writerow([
            f"{minute:.0f}", f"{app_mb:.1f}", f"{kids:.0f}", me.num_threads(), me.num_handles(),
            f"{me.cpu_percent(None) / logical_cpus:.2f}", vram_free_mib(), state,
        ])
        out.flush()
        samples.append((minute, app_mb, state))

    def turn() -> None:
        if teto._activity.state is Activity.GAME:
            counts["saltados"] += 1
            return
        number = counts["turnos"]
        counts["turnos"] += 1
        # Cada pocos turnos se fuerzan transiciones de estado, para probar cargas y descargas.
        if number % 5 == 3:
            teto._bus.suspend_requested.emit(True)
            QTimer.singleShot(60_000, lambda: teto._bus.suspend_requested.emit(False))
            return
        if number % 5 == 4:
            teto._bus.game_mode_requested.emit(True)
            QTimer.singleShot(60_000, lambda: teto._bus.game_mode_requested.emit(False))
            return
        teto._bus.user_message.emit(MESSAGES[number % len(MESSAGES)])

    sampler = QTimer()
    sampler.timeout.connect(sample)
    sampler.start(SAMPLE_SECONDS * 1000)
    talker = QTimer()
    talker.timeout.connect(turn)
    talker.start(int(args.minutos_entre_turnos * 60_000))
    QTimer.singleShot(int(args.horas * 3_600_000), app.quit)
    sample()
    app.exec()
    teto._shutdown()
    out.close()

    # La RAM en reposo se compara al principio y al final, fuera de los turnos.
    resting = [mb for _m, mb, state in samples if state in ("inactiva", "suspendida")]
    hour = max(1, len(resting) // 8)
    print(f"Duración: {(time.monotonic() - started) / 3600:.2f} h; datos en {args.salida}")
    print(f"Turnos {counts['turnos']}, respuestas {counts['respuestas']}, errores {counts['errores']}, "
          f"saltados por juego {counts['saltados']}")
    if len(resting) >= 2 * hour:
        first, last = statistics.median(resting[:hour]), statistics.median(resting[-hour:])
        print(f"RAM de la app en reposo: {first:.1f} MB al principio, {last:.1f} MB al final "
              f"({last - first:+.1f} MB)")
    print(f"RAM máxima de la app: {max(mb for _m, mb, _s in samples):.1f} MB")
    print(f"llama-server tras cerrar: {sum(c.name() == 'llama-server.exe' for c in me.children(True))}")
    print(f"Registro: {data / 'logs'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
