"""Decide qué nombre buscar en VocaDB y convierte el resultado en datos para el modelo."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from kasane_teto.memory.knowledge import normalize
from kasane_teto.tools.vocadb import Artist, Song, VocaDBClient, VocaDBError

DEFAULT_SONGS = 10
FEATURED_SONGS = 5
MAX_SONGS = 20
MAX_TOPIC_WORDS = 6
MAX_TOPIC_CHARS = 60
MAX_SONG_MATCHES = 2
UNAVAILABLE_FACT = (
    "VocaDB no respondió. Si preguntan por música virtual y no lo sabes con certeza, di que "
    "ahora no puedes comprobarlo y no inventes títulos ni nombres."
)

_COUNT_WORDS = {"cinco": 5, "diez": 10, "quince": 15, "veinte": 20}

_AUTHOR = re.compile(
    r"\bqui[eé]n(?:es)?\s+(?:hizo|compuso|cre[oó]|produjo|canta|cant[oó]|escribi[oó])\b"
    r"|\bde\s+qui[eé]n\s+es\b",
    re.IGNORECASE,
)
_INFO = re.compile(
    r"(?:\bqui[eé]n(?:es)?\s+(?:es|son|fue|era|hizo|compuso|cre[oó]|produjo|canta|cant[oó]"
    r"|escribi[oó])"
    r"|\bde\s+qui[eé]n\s+es"
    r"|\bqu[eé]\s+sabes\s+(?:de|del|sobre|acerca\s+de)"
    r"|\bh[aá]blame\s+(?:de|del|sobre|acerca\s+de)"
    r"|\bcu[eé]ntame\s+(?:de|del|sobre|acerca\s+de)"
    r"|\bconoces(?:\s+a)?"
    r"|\bb[uú]sca(?:me)?(?:\s+en\s+(?:internet|vocadb))?)"
    r"\s+(?P<topic>.+)",
    re.IGNORECASE | re.DOTALL,
)
_SONGS = re.compile(
    r"\b(?:canci[oó]n(?:es)?|temas)\b[^?!.]*?\b(?:de|del|por|tiene|tienen|hizo|ha\s+hecho|sac[oó])"
    r"\s+(?P<topic>.+)",
    re.IGNORECASE | re.DOTALL,
)
_COUNT = re.compile(r"\b(\d{1,2}|cinco|diez|quince|veinte)\s+(?:canciones|temas)\b", re.IGNORECASE)
_QUOTED = re.compile(r"[\"“«](.+?)[\"”»]")
_CLAUSE_END = re.compile(r"[?!.;,:¿¡\n]")
_LEADING_WORDS = re.compile(
    r"^(?:el|la|los|las|lo|un|una|a|al|de|del|sobre|canci[oó]n|tema|productor|productora"
    r"|cantante|artista|grupo|banda|compositor|compositora|vocaloid|utau|synthv)\s+",
    re.IGNORECASE,
)
_TRAILING_WORDS = re.compile(r"\s+(?:por\s+favor|porfa)$", re.IGNORECASE)
_SENSITIVE = re.compile(r"@|https?:|\d{6,}")

# Si el tema incluye una de estas palabras, habla de personas cercanas o de la propia Teto.
_PERSONAL_WORDS = frozenset(
    "yo mi mis me conmigo tu tus ti te contigo nosotros nuestro nuestra nuestros nuestras "
    "ella ellas ellos eso esto esa ese".split()
)

_KIND_NAMES = {
    "Producer": "productor",
    "Circle": "círculo musical",
    "Band": "grupo",
    "Vocalist": "cantante",
    "Utaite": "cantante humano de versiones (utaite)",
    "UTAU": "cantante virtual de UTAU",
    "Vocaloid": "cantante virtual de Vocaloid",
    "SynthesizerV": "cantante virtual de Synthesizer V",
    "CeVIO": "cantante virtual de CeVIO",
}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebQuery:
    topic: str
    wants_songs: bool = False
    count: int = DEFAULT_SONGS


@dataclass(frozen=True)
class WebResult:
    facts: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    failed: bool = False


def _clean_topic(raw: str) -> str | None:
    """Deja solo el nombre buscado; lo que parezca personal no sale del equipo."""
    quoted = _QUOTED.search(raw)
    topic = quoted.group(1) if quoted else _CLAUSE_END.split(raw, maxsplit=1)[0]
    topic = _TRAILING_WORDS.sub("", topic.strip(" \"'“”«»"))
    while (trimmed := _LEADING_WORDS.sub("", topic)) != topic:
        topic = trimmed
    words = normalize(topic).split()
    if not words or len(words) > MAX_TOPIC_WORDS or len(topic) > MAX_TOPIC_CHARS:
        return None
    if _SENSITIVE.search(topic) or _PERSONAL_WORDS.intersection(words):
        return None
    return topic


def _song_count(text: str) -> int:
    match = _COUNT.search(text)
    if match is None:
        return DEFAULT_SONGS
    value = match.group(1).casefold()
    count = _COUNT_WORDS.get(value) or int(value)
    return max(1, min(count, MAX_SONGS))


def parse_query(text: str) -> WebQuery | None:
    """Reconoce preguntas por artistas o canciones. Lo demás no se busca."""
    songs = _SONGS.search(text)
    if songs is not None and _AUTHOR.search(text) is None:
        topic = _clean_topic(songs.group("topic"))
        if topic is not None:
            return WebQuery(topic, wants_songs=True, count=_song_count(text))
    info = _INFO.search(text)
    if info is None:
        return None
    topic = _clean_topic(info.group("topic"))
    return WebQuery(topic) if topic is not None else None


def _song_titles(songs: Sequence[Song], numbered: bool = False) -> str:
    parts = []
    for position, song in enumerate(songs, start=1):
        details = ", ".join(value for value in (song.producer, song.year) if value)
        prefix = f"{position}. " if numbered else ""
        parts.append(f'{prefix}"{song.name}" ({details})')
    return "; ".join(parts)


def _artist_fact(artist: Artist, songs: Sequence[Song]) -> str:
    kind = _KIND_NAMES.get(artist.kind, "artista")
    fact = f"VocaDB, artista: {artist.name}. Tipo: {kind}."
    if artist.description:
        fact += f" Descripción en la web, en su idioma: {artist.description}"
    if songs:
        fact += f" Canciones mejor valoradas: {_song_titles(songs)}."
    return fact


def _song_fact(song: Song) -> str:
    fact = f'VocaDB, canción: "{song.name}". Productor: {song.producer}.'
    if song.voices:
        fact += f" Voz: {song.voices}."
    if song.year:
        fact += f" Publicada en {song.year}."
    return fact


def _no_songs_fact(query: WebQuery) -> tuple[str, ...]:
    """Pedir una lista sin datos la hace inventar títulos; en cultura general no hace falta."""
    if not query.wants_songs:
        return ()
    return (f"VocaDB no da canciones de {query.topic}: di que no las conoces y no inventes títulos.",)


class MusicLookup:
    def __init__(self, client: VocaDBClient) -> None:
        self._client = client

    def search(self, query: WebQuery) -> WebResult:
        try:
            result = self._artist_songs(query) if query.wants_songs else None
            result = result or self._details(query.topic)
        except VocaDBError as exc:
            log.warning("No se pudo consultar VocaDB: %s", exc)
            return WebResult((UNAVAILABLE_FACT,), failed=True)
        return result if result.facts else WebResult(_no_songs_fact(query))

    def _artist_songs(self, query: WebQuery) -> WebResult | None:
        artists = self._client.find_artists(query.topic, limit=1)
        if not artists:
            return None
        artist = artists[0]
        songs = self._client.top_songs(artist, query.count)
        if not songs:
            return None
        fact = (
            f"VocaDB, canciones mejor valoradas de {artist.name}, no es la lista completa. "
            f"Escribe estos títulos en tu respuesta: {_song_titles(songs, numbered=True)}."
        )
        return WebResult((fact,), (artist.url,))

    def _details(self, topic: str) -> WebResult:
        artists = self._client.find_artists(topic)
        songs = self._client.find_songs(topic, limit=MAX_SONG_MATCHES)
        facts = [
            _artist_fact(artist, self._client.top_songs(artist, FEATURED_SONGS) if not index else [])
            for index, artist in enumerate(artists)
        ]
        facts.extend(_song_fact(song) for song in songs)
        return WebResult(
            tuple(facts), tuple(item.url for item in (*artists, *songs))
        )
