"""Integración con llama-server y un modelo real: pytest -m slow"""

import threading

import pytest

from kasane_teto.ai.llm_client import GenerationParams, LLMClient
from kasane_teto.ai.llm_process import LLMConfig, LLMProcess
from kasane_teto.core.paths import models_dir
from kasane_teto.core.resource_manager import free_vram_mib
from kasane_teto.personality.emotion_parser import RESPONSE_GRAMMAR, EmotionParser

SERVER = models_dir() / "llama" / "llama-server.exe"
MODEL = models_dir() / "gguf" / "Qwen3.5-2B-Q4_K_M.gguf"

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not MODEL.exists(), reason="modelo no descargado")
def test_load_answer_and_release_vram(tmp_path):
    before = free_vram_mib()
    process = LLMProcess(LLMConfig(SERVER, MODEL, 2048, 99, 6, 120), tmp_path / "server.log")
    process.start()
    try:
        assert free_vram_mib() < before - 500
        parser = EmotionParser()
        text = "".join(
            parser.feed(chunk)
            for chunk in LLMClient(process.base_url, process.api_key).stream_chat(
                [{"role": "user", "content": "Di hola."}],
                GenerationParams(30, 0.2, RESPONSE_GRAMMAR),
                threading.Event(),
            )
        )
        assert text.strip()
        assert parser.emotion is not None
    finally:
        process.stop()
    assert not process.is_running
    assert free_vram_mib() >= before - 100
