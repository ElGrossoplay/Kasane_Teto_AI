"""Reproducción y grabación; sounddevice solo se importa cuando se usa."""

from __future__ import annotations

import array
import threading
from typing import Any

from kasane_teto.voice.worker_process import VoiceError

RECORD_RATE = 16000
PLAY_BLOCK_BYTES = 4096
SILENCE_PEAK = 500


def apply_volume(pcm: bytes, volume: int) -> bytes:
    """Escala audio de 16 bits; volume va de 0 a 100."""
    if volume >= 100:
        return pcm
    samples = array.array("h", pcm)
    return array.array("h", (s * volume // 100 for s in samples)).tobytes()


def is_silence(pcm: bytes) -> bool:
    samples = array.array("h", pcm)
    return not samples or max(map(abs, samples)) < SILENCE_PEAK


class AudioPlayer:
    def __init__(self) -> None:
        self._stream: Any = None

    def play(self, pcm: bytes, rate: int, volume: int, cancel: threading.Event) -> None:
        import sounddevice

        try:
            if self._stream is None or self._stream.samplerate != rate:
                self.close()
                self._stream = sounddevice.RawOutputStream(rate, channels=1, dtype="int16")
                self._stream.start()
            data = apply_volume(pcm, volume)
            for start in range(0, len(data), PLAY_BLOCK_BYTES):
                if cancel.is_set():
                    return
                self._stream.write(data[start:start + PLAY_BLOCK_BYTES])
        except sounddevice.PortAudioError as exc:
            self.close()
            raise VoiceError(f"No se pudo reproducir el audio: {exc}") from exc

    def close(self) -> None:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            stream.stop()
            stream.close()


class AudioRecorder:
    def __init__(self) -> None:
        self._stream: Any = None
        self._chunks: list[bytes] = []

    def _on_audio(self, data: Any, frames: int, time: Any, status: Any) -> None:
        self._chunks.append(bytes(data))

    def start(self) -> None:
        import sounddevice

        self._chunks = []
        try:
            self._stream = sounddevice.RawInputStream(
                RECORD_RATE, channels=1, dtype="int16", callback=self._on_audio
            )
            self._stream.start()
        except sounddevice.PortAudioError as exc:
            self._stream = None
            raise VoiceError(f"No se pudo abrir el micrófono: {exc}") from exc

    def stop(self) -> bytes:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            stream.stop()
            stream.close()
        return b"".join(self._chunks)
