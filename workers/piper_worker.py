"""Proceso aparte que mantiene una voz de Piper cargada y sintetiza frase a frase.

Se ejecuta con el Python de models/piper/venv, nunca dentro de la app. Usa la biblioteca
piper-tts, por lo que este archivo se distribuye bajo GPL-3.0-or-later.

Protocolo: entra una línea JSON por frase en stdin ({"text": ..., "length_scale": ...}).
Sale por stdout audio PCM de 16 bits en bloques con prefijo de longitud de 4 bytes
(little-endian); un bloque de longitud 0 marca el fin de la frase.
"""

import json
import struct
import sys

from piper import PiperVoice, SynthesisConfig


def main() -> int:
    voice = PiperVoice.load(sys.argv[1])
    output = sys.stdout.buffer
    print(json.dumps({"sample_rate": voice.config.sample_rate}), file=sys.stderr, flush=True)
    for line in sys.stdin.buffer:
        try:
            request = json.loads(line)
            config = SynthesisConfig(length_scale=request.get("length_scale"))
            for chunk in voice.synthesize(request["text"], syn_config=config):
                audio = chunk.audio_int16_bytes
                output.write(struct.pack("<I", len(audio)))
                output.write(audio)
        except (KeyError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr, flush=True)
        output.write(struct.pack("<I", 0))
        output.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
