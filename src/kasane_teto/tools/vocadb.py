"""Cliente de la API pública de VocaDB, con caché local y límite diario de consultas.

Solo recibe nombres de artistas o canciones: la conversación nunca sale del equipo.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from kasane_teto.memory.knowledge import normalize

API_URL = "https://vocadb.net/api"
SITE_URL = "https://vocadb.net"
USER_AGENT = "KasaneTetoAI/0.1 (+https://github.com/ElGrossoplay/Kasane_Teto_AI)"
CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 10.0  # la lista de una voz con muchas versiones ha tardado 6 s
CACHE_SECONDS = 7 * 24 * 3600
MAX_REQUESTS_PER_DAY = 200
MAX_DESCRIPTION_CHARS = 300
MIN_DESCRIPTION_CHARS = 60
MAX_TITLE_CHARS = 80

# Sin ilustradores, versionadores ni fans: un nombre parecido daría un resultado sin relación.
ARTIST_TYPES = (
    "Vocaloid,UTAU,CeVIO,SynthesizerV,NEUTRINO,VoiSona,NewType,Voiceroid,VOICEVOX,"
    "ACEVirtualSinger,AIVOICE,OtherVoiceSynthesizer,Producer,Circle,Band,Vocalist,Utaite"
)
SONG_TYPES = "Original,Remaster"
VOICE_TYPES = frozenset(
    "Vocaloid UTAU CeVIO SynthesizerV NEUTRINO VoiSona NewType Voiceroid VOICEVOX "
    "ACEVirtualSinger AIVOICE OtherVoiceSynthesizer".split()
)
MAX_VOICEBANK_LEVELS = 3

log = logging.getLogger(__name__)


class VocaDBError(Exception):
    """No se pudo obtener la respuesta de VocaDB."""


def clean_text(text: str, limit: int) -> str:
    """Quita enlaces y marcas: es texto de una web comunitaria que luego lee el modelo."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>\[\]]", "", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _biography(text: str) -> str:
    """Muchas descripciones son notas para editores, y el modelo las toma por hechos."""
    cleaned = clean_text(text, MAX_DESCRIPTION_CHARS)
    if len(cleaned) < MIN_DESCRIPTION_CHARS or not cleaned[0].isalpha():
        return ""
    return "" if cleaned.casefold().startswith("note") else cleaned


def _name_key(text: str) -> str:
    return re.sub(r"[\W_]", "", normalize(text))


def _matches(query: str, item: dict[str, Any]) -> bool:
    """VocaDB devuelve parecidos: solo vale el nombre exacto o uno de sus alias."""
    names = [str(item.get("name", "")), *str(item.get("additionalNames", "")).split(",")]
    key = _name_key(query)
    return any(_name_key(name) == key for name in names)


@dataclass(frozen=True)
class Artist:
    id: int
    name: str
    kind: str
    description: str

    @property
    def url(self) -> str:
        return f"{SITE_URL}/Ar/{self.id}"


@dataclass(frozen=True)
class Song:
    id: int
    name: str
    producer: str
    voices: str
    year: str

    @property
    def url(self) -> str:
        return f"{SITE_URL}/S/{self.id}"


def _artist(item: dict[str, Any]) -> Artist:
    return Artist(
        int(item["id"]),
        clean_text(str(item["name"]), MAX_TITLE_CHARS),
        str(item.get("artistType", "")),
        _biography(str(item.get("description", ""))),
    )


def _song(item: dict[str, Any]) -> Song:
    credits_text = clean_text(str(item.get("artistString", "")), MAX_TITLE_CHARS)
    producer, _, voices = credits_text.partition(" feat. ")
    if producer == "Various artists":
        producer = "varios artistas"
    return Song(
        int(item["id"]),
        clean_text(str(item["name"]), MAX_TITLE_CHARS),
        producer,
        voices,
        str(item.get("publishDate") or "")[:4],
    )


class VocaDBClient:
    def __init__(
        self, cache_path: Path, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._cache_path = cache_path
        self._transport = transport

    def find_artists(self, name: str, limit: int = 2) -> list[Artist]:
        data = self._get(
            "artists",
            {
                "query": name,
                "maxResults": 10,
                "sort": "SongRating",
                "preferAccurateMatches": "true",
                "artistTypes": ARTIST_TYPES,
                "fields": "AdditionalNames,Description",
                "lang": "Romaji",
            },
        )
        return [_artist(i) for i in data.get("items", []) if _matches(name, i)][:limit]

    def find_songs(self, name: str, limit: int = 2) -> list[Song]:
        data = self._get(
            "songs",
            {
                "query": name,
                "maxResults": 10,
                "sort": "RatingScore",
                "preferAccurateMatches": "true",
                "songTypes": SONG_TYPES,
                "fields": "AdditionalNames",
                "lang": "Romaji",
            },
        )
        return [_song(i) for i in data.get("items", []) if _matches(name, i)][:limit]

    def top_songs(self, artist: Artist, limit: int) -> list[Song]:
        params: dict[str, Any] = {
            "artistId[]": artist.id,
            "maxResults": limit,
            "sort": "RatingScore",
            "songTypes": SONG_TYPES,
            "lang": "Romaji",
        }
        # Con un productor, childVoicebanks llega a colgar la consulta más de 12 s.
        if artist.kind in VOICE_TYPES:
            params["artistId[]"] = self._root_voicebank(artist.id)
            params["childVoicebanks"] = "true"
        return [_song(item) for item in self._get("songs", params).get("items", [])]

    def _root_voicebank(self, artist_id: int) -> int:
        """Cada versión de una voz cuelga de otra: Kasane Teto SV no es hija de la de UTAU."""
        for _ in range(MAX_VOICEBANK_LEVELS):
            data = self._get(f"artists/{artist_id}", {"fields": "BaseVoicebank"})
            base = data.get("baseVoicebank")
            if not isinstance(base, dict) or "id" not in base:
                break
            artist_id = int(base["id"])
        return artist_id

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        key = f"{path}?{urlencode(sorted(params.items()))}"
        try:
            with closing(sqlite3.connect(self._cache_path)) as db, db:
                self._prepare(db)
                cached = self._read_cache(db, key)
                if cached is not None:
                    return cached
                self._count_request(db)
            data = self._fetch(path, params)
            with closing(sqlite3.connect(self._cache_path)) as db, db:
                db.execute(
                    "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                    (key, json.dumps(data, ensure_ascii=False), time.time()),
                )
            return data
        except sqlite3.Error as exc:
            raise VocaDBError(f"Caché no disponible: {exc}") from exc

    @staticmethod
    def _prepare(db: sqlite3.Connection) -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS responses "
            "(key TEXT PRIMARY KEY, body TEXT NOT NULL, fetched_at REAL NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS requests (day TEXT PRIMARY KEY, total INTEGER NOT NULL)"
        )
        db.execute("DELETE FROM responses WHERE fetched_at < ?", (time.time() - CACHE_SECONDS,))

    @staticmethod
    def _read_cache(db: sqlite3.Connection, key: str) -> dict[str, Any] | None:
        row = db.execute("SELECT body FROM responses WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _count_request(db: sqlite3.Connection) -> None:
        today = date.today().isoformat()
        row = db.execute("SELECT total FROM requests WHERE day = ?", (today,)).fetchone()
        total = row[0] if row else 0
        if total >= MAX_REQUESTS_PER_DAY:
            raise VocaDBError("Límite diario de consultas alcanzado")
        db.execute("DELETE FROM requests WHERE day <> ?", (today,))
        db.execute("INSERT OR REPLACE INTO requests VALUES (?, ?)", (today, total + 1))

    def _fetch(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                transport=self._transport,
            ) as client:
                response = client.get(f"{API_URL}/{path}", params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VocaDBError(str(exc)) from exc
        if not isinstance(data, dict):
            raise VocaDBError("Respuesta con formato inesperado")
        return data
