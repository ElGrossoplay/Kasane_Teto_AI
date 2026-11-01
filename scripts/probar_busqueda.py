"""Mide si Teto usa bien los datos de VocaDB, con la API y el modelo reales.

Uso: .venv\\Scripts\\python.exe scripts\\probar_busqueda.py
Hace pocas consultas y guarda las respuestas en la caché de esta prueba.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from probar_conocimiento import local_model, run_checks  # noqa: E402

from kasane_teto.core.paths import knowledge_root, models_dir  # noqa: E402
from kasane_teto.memory.knowledge import KnowledgeBase, wants_opinion  # noqa: E402
from kasane_teto.personality.prompt_builder import knowledge_block  # noqa: E402
from kasane_teto.tools.vocadb import VocaDBClient  # noqa: E402
from kasane_teto.tools.web_lookup import (  # noqa: E402
    MusicLookup,
    WebResult,
    bare_topic,
    parse_query,
)

CACHE = models_dir() / "pruebas" / "vocadb_cache.sqlite3"

# (pregunta, cada grupo necesita al menos uno de sus textos, textos prohibidos)
CHECKS: list[tuple[str, list[list[str]], list[str]]] = [
    ("Dime 5 canciones de Kikuo", [["aishite"], ["gomenne"]], []),
    ("Nombra 20 canciones de Kasane Teto", [["mesmerizer"], ["machine love"], ["tetoris"]], []),
    ("¿Quién hizo Senbonzakura?", [["kurousa"]], []),
    ("¿Quién hizo Rolling Girl?", [["wowaka"]], []),
    ("¿Quién es Solaria?", [["synthesizer v", "synth"]], []),
    # Transcripciones reales de la prueba de Diego.
    ("Dime kienes kikuo.", [["productor"], ["aishite", "gomenne", "anagura"]], ["mascota", "gen "]),
    ("Quienes Kikuu.", [["productor"]], ["mascota", "gen "]),
    ("Gen es Kikuho.", [["productor"]], ["mascota"]),
    ("¿Quién es Kiku?", [["productor"]], ["kadokama"]),
    ("Estoy preguntando por KikuO el productor de canciones de Vocaloid.", [["aishite", "gomenne", "anagura"]], ["yamaha"]),
    ("Kienes Mili.", [["grupo", "banda"]], ["sailor", "tuxedo"]),
    ("¿Quién hizo Sembo Sakura? No, perdón. Si, Sembo Sakura.", [["kurousa"]], []),
    ("senbozakura", [["kurousa", "miku"]], []),
    ("¿Quién hizo sembo segura?", [["no lo conozco", "no conozco", "no tengo", "no se"]], ["kikuo", "yamaha", "vocalista"]),
    # Cultura general: el aviso de "VocaDB no lo conoce" no debe estropearla.
    ("¿Quién escribió Don Quijote?", [["cervantes"]], []),
    ("¿Quién es Albert Einstein?", [["fisic"]], []),
    ("¿Quién es Mitchie M?", [["productor"]], []),
    ("¿Qué canciones tiene el productor Tanuki-P?", [["no lo conozco", "no conozco", "no tengo", "no se"]], []),
    ("¿Cuál es la capital de Japón?", [["tokio", "tokyo"]], ["vocadb"]),
    ("Estoy cansado, hoy el trabajo fue horrible.", [], ["vocadb", "cancion"]),
]


def main() -> int:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    knowledge = KnowledgeBase.load(knowledge_root())
    lookup = MusicLookup(VocaDBClient(CACHE))

    def build_message(question: str) -> str:
        query = parse_query(question)
        topic = query.topic if query is not None else bare_topic(question)
        named = knowledge.by_name(topic or question) or (
            knowledge.by_similar_name(topic) if topic else []
        )
        entries = named or knowledge.by_keywords(question)
        web = WebResult()
        if query is not None and (query.wants_songs or not named):
            started = time.monotonic()
            web = lookup.search(query)
            print(f"  VocaDB {query}: {time.monotonic() - started:.2f} s, falló={web.failed}")
            for fact in web.facts:
                print(f"    {fact}")
        return knowledge_block(entries, wants_opinion(question), web.facts) + question

    with local_model() as ask:
        run_checks(ask, CHECKS, build_message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
