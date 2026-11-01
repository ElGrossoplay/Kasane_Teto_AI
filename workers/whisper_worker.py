"""Proceso aparte que mantiene faster-whisper cargado: cerrarlo libera toda su memoria.

Se ejecuta con el Python de models/whisper/venv, nunca dentro de la app.

Protocolo: entra por stdin audio PCM de 16 bits, mono y 16 kHz, con prefijo de longitud de
4 bytes (little-endian). Sale por stdout una línea JSON con {"text": ...} por cada audio.
"""

import json
import struct
import sys

import numpy as np
from faster_whisper import WhisperModel

LANGUAGE = "es"


def read_exact(stream, size: int) -> bytes | None:
    data = stream.read(size)
    return data if len(data) == size else None


def main() -> int:
    model = WhisperModel(sys.argv[1], device="cpu", compute_type="int8", cpu_threads=int(sys.argv[2]))
    vocabulary = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps({"ready": True}), file=sys.stderr, flush=True)
    while True:
        header = read_exact(sys.stdin.buffer, 4)
        if header is None:
            return 0
        pcm = read_exact(sys.stdin.buffer, struct.unpack("<I", header)[0])
        if pcm is None:
            return 0
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio,
            language=LANGUAGE,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=vocabulary,
        )
        text = "".join(segment.text for segment in segments).strip()
        print(json.dumps({"text": text}), flush=True)


if __name__ == "__main__":
    sys.exit(main())
