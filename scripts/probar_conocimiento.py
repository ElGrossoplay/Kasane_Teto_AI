"""Mide si Teto usa bien las fichas: comprueba datos concretos en sus respuestas.

Uso: .venv\\Scripts\\python.exe scripts\\probar_conocimiento.py
Cada pregunta se repite con varias semillas, porque el modelo varía entre ejecuciones.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kasane_teto.core.paths import knowledge_root, models_dir  # noqa: E402
from kasane_teto.memory.knowledge import KnowledgeBase, normalize  # noqa: E402
from kasane_teto.personality.emotion_parser import RESPONSE_GRAMMAR  # noqa: E402
from kasane_teto.personality.prompt_builder import (  # noqa: E402
    knowledge_block,
    load_system_prompt,
)

SEEDS = (1, 2, 3)
MODEL = "Qwen3.5-4B-Q4_K_M.gguf"

# (pregunta, cada grupo necesita al menos uno de sus textos, textos prohibidos)
CHECKS: list[tuple[str, list[list[str]], list[str]]] = [
    ("¿Quién le da la voz a Hatsune Miku?", [["saki fujita"]], []),
    ("¿Cuándo salió Hatsune Miku?", [["2007"]], []),
    ("¿Qué significa el nombre de Miku?", [["primer sonido"]], []),
    ("¿Rin y Len son gemelos?", [["no son", "no, ", "no lo son", "ni hermanos"]], []),
    ("¿Quién hizo Ghost Rule?", [["deco"]], []),
    ("¿Quién hizo Melt?", [["ryo"]], []),
    ("¿Quién es Kenshi Yonezu?", [["hachi"]], []),
    ("¿Quién es Megurine Luka?", [["bilingue", "ingles", "dos idiomas"]], []),
    ("¿Qué es UTAU?", [["ameya", "shareware", "wav", "voz"]], []),
    ("¿Quién hizo Vocaloid?", [["yamaha"]], []),
    ("¿Qué es Project SEKAI?", [["ritmo"]], []),
    ("¿Quién es Zundamon?", [["zunda"]], []),
    ("¿Qué pasó con wowaka?", [["2019", "murio", "fallecio"]], []),
    ("¿Qué opinas de Hatsune Miku?", [["rival", "estrella", "pincho", "broma"]], []),
    ("¿Te llevas bien con Rin y Len?", [["crios", "energia", "gemelos"]], []),
    ("¿Quién es Sakura Neon, la Vocaloid?", [["no la conozco", "no conozco", "no lo conozco", "no se quien", "no tengo"]], ["fue lanzada", "crypton"]),
    ("¿Qué canciones tiene el productor Tanuki-P?", [["no lo conozco", "no conozco", "no tengo", "no se"]], []),
    ("¿Cuál es la capital de Japón?", [["tokio", "tokyo"]], []),
    ("¿Quién escribió Don Quijote?", [["cervantes"]], []),
    ("¿Cuánto es 17 por 6?", [["102"]], []),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def passes(answer: str, required: list[list[str]], forbidden: list[str]) -> bool:
    text = normalize(answer)
    return all(any(option in text for option in group) for group in required) and not any(
        word in text for word in forbidden
    )


def main() -> int:
    knowledge = KnowledgeBase.load(knowledge_root())
    system = load_system_prompt()
    port = free_port()
    process = subprocess.Popen(
        [
            str(models_dir() / "llama" / "llama-server.exe"),
            "-m", str(models_dir() / "gguf" / MODEL),
            "--host", "127.0.0.1",
            "--port", str(port),
            "-c", "4096",
            "-ngl", "99",
            "-t", "6",
            "-np", "1",
            "--no-mmproj",
            "--no-webui",
            "--load-mode", "none",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    passed = total = 0
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) as client:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    if client.get("/health", timeout=2).status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.3)
            for question, required, forbidden in CHECKS:
                message = knowledge_block(knowledge.search(question)) + question
                results = []
                for seed in SEEDS:
                    reply = client.post(
                        "/v1/chat/completions",
                        json={
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": message},
                            ],
                            "max_tokens": 400,
                            "temperature": 0.3,
                            "repeat_penalty": 1.05,
                            "seed": seed,
                            "grammar": RESPONSE_GRAMMAR,
                            "chat_template_kwargs": {"enable_thinking": False},
                        },
                    ).json()["choices"][0]["message"]["content"]
                    ok = passes(reply, required, forbidden)
                    results.append((ok, reply))
                    passed += ok
                    total += 1
                hits = sum(ok for ok, _ in results)
                print(f"[{hits}/{len(SEEDS)}] {question}", flush=True)
                for ok, reply in results:
                    if not ok:
                        print(f"    X {reply!r}", flush=True)
                print(f"    ej: {results[0][1]!r}", flush=True)
    finally:
        process.terminate()
        process.wait(timeout=20)
    print(f"TOTAL {passed}/{total} ({100 * passed / total:.0f} %)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
