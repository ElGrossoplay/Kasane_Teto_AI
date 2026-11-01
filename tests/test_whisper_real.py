"""Integración con faster-whisper real: pytest -m slow"""

import array
import math

import pytest

from kasane_teto.core.paths import models_dir, workers_dir
from kasane_teto.voice.audio import Recording
from kasane_teto.voice.engines import STTEngine

pytestmark = pytest.mark.slow


@pytest.mark.skipif(
    not (models_dir() / "whisper" / "small" / "model.bin").exists(), reason="modelo no descargado"
)
def test_stereo_48k_audio_reaches_the_recognizer():
    samples = array.array("h")
    for index in range(48000):
        value = int(8000 * math.sin(2 * math.pi * 440 * index / 48000))
        samples.extend((value, value))
    engine = STTEngine(models_dir(), workers_dir(), 2, "Vocaloid")
    try:
        assert isinstance(engine.transcribe(Recording(samples.tobytes(), 48000, 2)), str)
    finally:
        engine.unload()
