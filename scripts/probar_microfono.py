"""Mide el reconocimiento con tu voz real. El audio se queda en tu equipo, fuera de git.

Grabar y medir:   .venv\\Scripts\\python.exe scripts\\probar_microfono.py
Solo volver a medir lo grabado:   .venv\\Scripts\\python.exe scripts\\probar_microfono.py --sin-grabar
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kasane_teto.core.paths import knowledge_root, models_dir, workers_dir  # noqa: E402
from kasane_teto.memory.knowledge import KnowledgeBase, normalize  # noqa: E402
from kasane_teto.voice.audio import AudioRecorder, Recording  # noqa: E402
from kasane_teto.voice.engines import STTEngine  # noqa: E402

FOLDER = models_dir() / "pruebas" / "microfono"
PHRASES = [
    "Háblame sobre Vocaloid.",
    "¿Quién es Hatsune Miku?",
    "Cuéntame un chiste corto.",
    "¿Qué opinas de Kagamine Rin y Len?",
    "¿Qué me recomiendas hacer esta noche?",
    "Hoy tuve un día bastante pesado en el trabajo.",
    "¿Cuál es la canción más famosa de DECO*27?",
    "Explícame qué es la memoria RAM.",
    "¿Quién es Kikuo?",
    "¿Quién hizo Senbonzakura?",
    "Dime cinco canciones de Mitchie M.",
    "¿Quién es Mili?",
]


def record_all(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    recorder = AudioRecorder()
    print("Lee cada frase con tu voz y velocidad normales.\n")
    for index, phrase in enumerate(PHRASES):
        input(f"[{index + 1}/{len(PHRASES)}] Pulsa Enter y di: {phrase}")
        recorder.start()
        input("   Grabando… pulsa Enter al terminar.")
        recording = recorder.stop()
        with wave.open(str(folder / f"{index}.wav"), "wb") as file:
            file.setnchannels(recording.channels)
            file.setsampwidth(2)
            file.setframerate(recording.rate)
            file.writeframes(recording.pcm)


def load(path: Path) -> Recording:
    with wave.open(str(path)) as file:
        return Recording(
            file.readframes(file.getnframes()), file.getframerate(), file.getnchannels()
        )


def similarity(expected: str, heard: str) -> float:
    words = re.findall(r"\w+", normalize(expected))
    other = re.findall(r"\w+", normalize(heard))
    return difflib.SequenceMatcher(None, words, other).ratio()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sin-grabar", action="store_true")
    parser.add_argument("--carpeta", type=Path, default=FOLDER)
    parser.add_argument("--hilos", type=int, default=4)
    args = parser.parse_args()
    if not args.sin_grabar:
        record_all(args.carpeta)

    vocabulary = KnowledgeBase.load(knowledge_root()).vocabulary()
    installed = [p.name for p in sorted((models_dir() / "whisper").iterdir()) if (p / "model.bin").is_file()]
    for model in installed:
        engine = STTEngine(models_dir(), workers_dir(), args.hilos, vocabulary, model)
        print(f"\n=== modelo {model} ===")
        started = time.monotonic()
        engine.load()
        print(f"carga {time.monotonic() - started:.1f} s")
        scores = []
        for index, phrase in enumerate(PHRASES):
            path = args.carpeta / f"{index}.wav"
            if not path.exists():
                continue
            recording = load(path)
            started = time.monotonic()
            heard = engine.transcribe(recording)
            elapsed = time.monotonic() - started
            score = similarity(phrase, heard)
            scores.append(score)
            print(f"{score:4.0%} {elapsed:4.1f} s ({recording.seconds:.1f} s de audio) | {heard}")
        engine.unload()
        if scores:
            print(f"Coincidencia media: {sum(scores) / len(scores):.0%}")
    print("\nCopia todo este texto y pégalo en el chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
