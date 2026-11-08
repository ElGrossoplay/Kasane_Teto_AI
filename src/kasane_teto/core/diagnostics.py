"""Diagnóstico: `KasaneTetoAI.exe --diagnostico` comprueba que la app encuentra todo lo que usa y
que la IA responde. Escribe el informe en la carpeta de datos y no toca nada más."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from kasane_teto.core.paths import (
    character_root,
    default_config_path,
    knowledge_root,
    models_dir,
    workers_dir,
)
from kasane_teto.core.settings import Settings
from kasane_teto.personality import prompt_builder

REPORT_NAME = "diagnostico.txt"

log = logging.getLogger(__name__)


def _file_checks(settings: Settings) -> list[tuple[str, Path]]:
    models = models_dir()
    whisper = str(settings.get("voice.stt_model", "large-v3-turbo"))
    voice = str(settings.get("voice.model", "es_MX-claude-high"))
    checks = [
        ("Configuración", default_config_path()),
        ("Fichas de conocimiento", knowledge_root()),
        ("Personajes", character_root()),
        ("Prompt de Teto", Path(prompt_builder.__file__).parent / "prompts" / "teto.txt"),
        ("llama-server", models / "llama" / "llama-server.exe"),
        ("Modelo de GPU", models / "gguf" / str(settings.get("ai.gpu_model"))),
        ("Modelo de CPU", models / "gguf" / str(settings.get("ai.cpu_model"))),
        ("Visión", models / "gguf" / str(settings.get("ai.vision_model"))),
        ("Python de Piper", models / "piper" / "venv" / "Scripts" / "python.exe"),
        ("Voz de Piper", models / "piper" / "voices" / f"{voice}.onnx"),
        ("Python de Whisper", models / "whisper" / "venv" / "Scripts" / "python.exe"),
        ("Modelo de Whisper", models / "whisper" / whisper),
        ("Procesos de voz", workers_dir() / "piper_worker.py"),
    ]
    live2d = str(settings.get("pet.live2d_model", "") or "")
    if live2d:
        checks.append(("Modelo Live2D", Path(live2d)))
    return checks


def _module_checks() -> list[tuple[str, Callable[[], object]]]:
    def live2d_shaders() -> object:
        import live2d

        path = Path(live2d.__file__).parent / "FrameworkShaders" / "VertShaderSrc.vert"
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def pptx_template() -> object:
        from pptx import Presentation

        return Presentation()

    return [("Sombreadores de Live2D", live2d_shaders), ("Plantilla de PowerPoint", pptx_template)]


def run(settings: Settings, user_dir: Path, ask_ai: bool = True) -> bool:
    lines = [f"Diagnóstico de Kasane Teto AI, {time.strftime('%Y-%m-%d %H:%M')}"]
    ok = True
    for label, path in _file_checks(settings):
        found = path.exists()
        ok &= found or label in ("Visión", "Modelo Live2D")
        lines.append(f"{'OK ' if found else 'FALTA'} {label}: {path}")
    for label, check in _module_checks():
        try:
            check()
            lines.append(f"OK  {label}")
        except Exception as exc:  # el informe debe seguir aunque falle una pieza
            ok = False
            lines.append(f"FALLA {label}: {exc}")
    if ask_ai:
        ok &= _ask_ai(settings, user_dir, lines)
    lines.append("Resultado: todo correcto" if ok else "Resultado: hay problemas")
    report = user_dir / REPORT_NAME
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Diagnóstico escrito en %s", report)
    return ok


def _ask_ai(settings: Settings, user_dir: Path, lines: list[str]) -> bool:
    from kasane_teto.ai.llm_client import GenerationParams, LLMClient
    from kasane_teto.core.resource_manager import ResourceManager

    manager = ResourceManager(settings, models_dir(), user_dir / "logs" / "llama-server.log")
    started = time.monotonic()
    try:
        process = manager.ensure_loaded()
        params = GenerationParams(max_tokens=30, temperature=0.0, repeat_penalty=1.0)
        messages = [{"role": "user", "content": "Responde solo: hola"}]
        client = LLMClient(process.base_url, process.api_key)
        answer = "".join(client.stream_chat(messages, params, threading.Event()))
        lines.append(
            f"OK  IA ({manager._profile_name}) respondió en {time.monotonic() - started:.1f} s: "
            f"{answer.strip()[:60]!r}"
        )
        return bool(answer.strip())
    except Exception as exc:
        lines.append(f"FALLA IA: {exc}")
        return False
    finally:
        manager.shutdown()
