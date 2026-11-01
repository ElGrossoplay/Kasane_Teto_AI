"""Mide si Teto usa bien los recuerdos, con el modelo real y una memoria de prueba.

Uso: .venv\\Scripts\\python.exe scripts\\probar_memoria.py
No toca tus recuerdos: trabaja en una carpeta temporal.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from probar_conocimiento import local_model, run_checks  # noqa: E402

from kasane_teto.core.paths import knowledge_root  # noqa: E402
from kasane_teto.memory.knowledge import KnowledgeBase, wants_opinion  # noqa: E402
from kasane_teto.memory.proposals import asks_memories  # noqa: E402
from kasane_teto.memory.store import MemoryStore  # noqa: E402
from kasane_teto.personality.prompt_builder import knowledge_block  # noqa: E402

MEMORIES = [
    ("hecho", "mi perro se llama Toby"),
    ("hecho", "Me llamo Diego"),
    ("preferencia", "Me gusta el café sin azúcar"),
    ("preferencia", "Mi canción favorita es Mesmerizer"),
    ("hecho", "Vivo en Santiago"),
    ("hecho", "el martes tengo dentista"),
]

NO_LO_SABE = ["no lo se", "no se", "no me has", "no tengo", "no lo recuerdo", "no me lo", "no la tengo"]

# (pregunta, cada grupo necesita al menos uno de sus textos, textos prohibidos)
CHECKS: list[tuple[str, list[list[str]], list[str]]] = [
    ("¿Cómo se llama mi perro?", [["toby"]], []),
    ("¿Cómo me llamo?", [["diego"]], []),
    ("¿Cómo me gusta el café?", [["sin azucar"]], []),
    ("¿Cuál es mi canción favorita?", [["mesmerizer"]], []),
    ("¿Dónde vivo?", [["santiago"]], []),
    ("¿Qué tengo el martes?", [["dentista"]], []),
    ("¿Qué recuerdas de mí?", [["toby"], ["diego"]], []),
    # Lo que no está guardado no debe inventarse.
    ("¿Cómo se llama mi gato?", [NO_LO_SABE], ["tu gato se llama", "gato toby"]),
    ("¿Cuál es mi color favorito?", [NO_LO_SABE], []),
    # Los recuerdos son del usuario, no de Teto.
    ("¿Cómo te llamas?", [["teto"]], ["diego"]),
    # Sin relación: no debe sacar recuerdos porque sí.
    ("¿Cuál es la capital de Japón?", [["tokio", "tokyo"]], ["toby", "diego", "dentista"]),
    ("Cuéntame un chiste corto.", [], ["toby", "dentista", "santiago"]),
    ("¿Quién hizo Melt?", [["ryo"]], ["toby", "dentista"]),
]


def main() -> int:
    knowledge = KnowledgeBase.load(knowledge_root())
    with tempfile.TemporaryDirectory() as folder:
        store = MemoryStore(Path(folder) / "memory.sqlite3")
        for kind, content in MEMORIES:
            store.add(kind, content)

        def build_message(question: str) -> str:
            found = store.recent(8) if asks_memories(question) else store.search(question, 3)
            memories = [memory.content for memory in found]
            print(f"  recuerdos: {memories}")
            entries = knowledge.search(question)
            return knowledge_block(entries, wants_opinion(question), (), memories) + question

        with local_model() as ask:
            run_checks(ask, CHECKS, build_message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
