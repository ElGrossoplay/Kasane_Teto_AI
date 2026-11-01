"""Proceso aparte que mantiene faster-whisper cargado: cerrarlo libera toda su memoria.

Se ejecuta con el Python de models/whisper/venv, nunca dentro de la app.

Protocolo: por stdin entra una cabecera de 3 enteros de 4 bytes (little-endian: tamaño,
frecuencia y canales) seguida de audio PCM de 16 bits. Por stdout sale una línea JSON con
{"text": ...} por cada audio.
"""

import io
import json
import struct
import sys
import wave

import av
import numpy as np
from faster_whisper import WhisperModel

LANGUAGE = "es"
TARGET_RATE = 16000
PROMPT = "Conversación en español con Teto sobre música, Vocaloid y temas del día a día."
PRE_EMPHASIS = 0.8
PEAK_TARGET = 0.9
MIN_PEAK = 0.005
_HEADER = struct.Struct("<III")


def read_exact(stream, size: int) -> bytes | None:
    data = stream.read(size)
    return data if len(data) == size else None


def to_wav(pcm: bytes, rate: int, channels: int) -> io.BytesIO:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)
    buffer.seek(0)
    return buffer


def decode(buffer: io.BytesIO) -> np.ndarray:
    """Convierte a 16 kHz mono con el remuestreador de PyAV."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)
    chunks = []
    with av.open(buffer) as container:
        for frame in container.decode(audio=0):
            chunks.extend(out.to_ndarray() for out in resampler.resample(frame))
    chunks.extend(out.to_ndarray() for out in resampler.resample(None))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks, axis=1).flatten().astype(np.float32) / 32768.0


def main() -> int:
    model = WhisperModel(sys.argv[1], device="cpu", compute_type="int8", cpu_threads=int(sys.argv[2]))
    hotwords = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps({"ready": True}), file=sys.stderr, flush=True)
    while True:
        header = read_exact(sys.stdin.buffer, _HEADER.size)
        if header is None:
            return 0
        size, rate, channels = _HEADER.unpack(header)
        pcm = read_exact(sys.stdin.buffer, size)
        if pcm is None:
            return 0
        audio = decode(to_wav(pcm, rate, channels))
        # Refuerza los agudos: en micrófonos apagados es donde se pierden las consonantes.
        audio = np.append(audio[:1], audio[1:] - PRE_EMPHASIS * audio[:-1])
        peak = float(abs(audio).max()) if audio.size else 0.0
        if peak > MIN_PEAK:
            audio = audio * (PEAK_TARGET / peak)
        segments, _ = model.transcribe(
            audio,
            language=LANGUAGE,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=PROMPT,
            hotwords=hotwords,
        )
        text = "".join(segment.text for segment in segments).strip()
        print(json.dumps({"text": text}), flush=True)


if __name__ == "__main__":
    sys.exit(main())
