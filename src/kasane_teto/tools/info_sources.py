"""Información general en Internet: Wikipedia, Wikcionario, Open-Meteo, Frankfurter, AniList y
Open Library. Son APIs públicas, gratuitas y sin clave, con caché local y límite diario.

Solo reciben el término buscado (un nombre, una palabra, una ciudad o dos monedas): la
conversación y los recuerdos nunca salen del equipo.
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
from urllib.parse import quote, urlencode

import httpx

from kasane_teto.memory.knowledge import MIN_NAME_SIMILARITY, name_similarity, normalize
from kasane_teto.tools.vocadb import USER_AGENT, clean_text
from kasane_teto.tools.web_lookup import WebResult, clean_topic

WIKI = "wiki"
DEFINE = "define"
WEATHER = "weather"
CURRENCY = "currency"
ANIME = "anime"
MANGA = "manga"
BOOK = "book"

WIKIPEDIA_API = "https://es.wikipedia.org/w/api.php"
WIKTIONARY_API = "https://es.wiktionary.org/w/api.php"
GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
CURRENCY_API = "https://api.frankfurter.dev/v2/rate"
ANILIST_API = "https://graphql.anilist.co"
OPENLIBRARY_API = "https://openlibrary.org/search.json"

CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 8.0
MAX_REQUESTS_PER_DAY = 300
MAX_EXTRACT_CHARS = 600
MAX_SYNOPSIS_CHARS = 450
WIKI_RESULTS = 3
HOUR = 3600
# Cada fuente caduca a su ritmo: el tiempo cambia en minutos y una biografía en semanas.
CACHE_SECONDS = {
    WIKI: 7 * 24 * HOUR,
    DEFINE: 30 * 24 * HOUR,
    "geocoding": 30 * 24 * HOUR,
    WEATHER: HOUR // 2,
    CURRENCY: 6 * HOUR,
    ANIME: 24 * HOUR,  # AniList prohíbe usar su API como almacén de datos
    BOOK: 7 * 24 * HOUR,
}

PROVIDERS = {
    WIKI: "Wikipedia (CC BY-SA 4.0)",
    DEFINE: "Wikcionario (CC BY-SA 4.0)",
    WEATHER: "Open-Meteo.com (CC BY 4.0)",
    CURRENCY: "Frankfurter",
    ANIME: "AniList",
    MANGA: "AniList",
    BOOK: "Open Library",
}

# Códigos WMO que devuelve Open-Meteo.
WEATHER_CODES = {
    0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha", 51: "llovizna débil", 53: "llovizna",
    55: "llovizna intensa", 56: "llovizna helada", 57: "llovizna helada intensa",
    61: "lluvia débil", 63: "lluvia", 65: "lluvia fuerte", 66: "lluvia helada",
    67: "lluvia helada fuerte", 71: "nevada débil", 73: "nevada", 75: "nevada fuerte",
    77: "granizo menudo", 80: "chubascos débiles", 81: "chubascos", 82: "chubascos fuertes",
    85: "chubascos de nieve", 86: "chubascos de nieve fuertes", 95: "tormenta",
    96: "tormenta con granizo", 99: "tormenta con granizo fuerte",
}

# Nombre en español → código ISO. "Peso" a secas se toma por el mexicano y se dice así.
CURRENCIES = {
    "dolar estadounidense": "USD", "dolares estadounidenses": "USD", "dolar americano": "USD",
    "dolares americanos": "USD", "dolar": "USD", "dolares": "USD",
    "euro": "EUR", "euros": "EUR",
    "peso mexicano": "MXN", "pesos mexicanos": "MXN", "peso argentino": "ARS",
    "pesos argentinos": "ARS", "peso chileno": "CLP", "pesos chilenos": "CLP",
    "peso colombiano": "COP", "pesos colombianos": "COP", "peso uruguayo": "UYU",
    "pesos uruguayos": "UYU", "peso": "MXN", "pesos": "MXN",
    "yen": "JPY", "yenes": "JPY", "libra": "GBP", "libras": "GBP", "yuan": "CNY",
    "yuanes": "CNY", "won": "KRW", "wones": "KRW", "real": "BRL", "reales": "BRL",
    "sol": "PEN", "soles": "PEN", "franco suizo": "CHF", "francos suizos": "CHF",
    "rupia": "INR", "rupias": "INR", "quetzal": "GTQ", "quetzales": "GTQ",
}
CURRENCY_NAMES = {
    "USD": "dólares estadounidenses", "EUR": "euros", "MXN": "pesos mexicanos",
    "ARS": "pesos argentinos", "CLP": "pesos chilenos", "COP": "pesos colombianos",
    "UYU": "pesos uruguayos", "JPY": "yenes", "GBP": "libras esterlinas", "CNY": "yuanes",
    "KRW": "wones", "BRL": "reales", "PEN": "soles", "CHF": "francos suizos", "INR": "rupias",
    "GTQ": "quetzales",
}

_CURRENCY_WORDS = "|".join(sorted(CURRENCIES, key=len, reverse=True))
_CONVERT = re.compile(
    rf"(?:(?P<amount>\d+(?:[.,]\d+)?)\s+)?(?P<source>{_CURRENCY_WORDS})\s+(?:a|en)\s+"
    rf"(?P<target>{_CURRENCY_WORDS})\b"
)
_CURRENCY_PRICE = re.compile(
    rf"\b(?:a\s+cuanto\s+esta|cuanto\s+(?:esta|vale|cuesta)|precio\s+del?|cambio\s+del?"
    rf"|tipo\s+de\s+cambio\s+del?)\s+(?:el\s+|la\s+)?(?P<source>{_CURRENCY_WORDS})\b"
    rf"(?:\s+(?:en|a)\s+(?P<target>{_CURRENCY_WORDS})\b)?"
)
_WEATHER = re.compile(
    r"\b(?:que\s+tiempo\s+(?:hace|hara|va\s+a\s+hacer)|el\s+tiempo|que\s+clima|el\s+clima"
    r"|temperatura|pronostico|va\s+a\s+llover|llovera|llueve|hace\s+(?:frio|calor))\b"
)
_CITY = re.compile(r"\ben\s+(?P<city>[a-zñü][a-zñü .'-]{1,40})")
_CITY_NOISE = re.compile(r"\s+(?:hoy|manana|ahora|esta\s+(?:tarde|noche|semana))\b.*$")
_DEFINE = re.compile(
    r"\b(?:que\s+significa(?:\s+la\s+palabra)?|que\s+quiere\s+decir|significado\s+de"
    r"(?:\s+la\s+palabra)?|definicion\s+de(?:\s+la\s+palabra)?|define(?:\s+la\s+palabra)?)\s+"
    r"(?P<topic>.+)",
    re.DOTALL,
)
_MEDIA = re.compile(
    r"\b(?P<kind>anime|manga|libro|novela)\s+(?:de\s+|del\s+|llamad[oa]\s+|que\s+se\s+llama\s+)?"
    r"(?P<topic>.+)",
    re.DOTALL,
)
_MEDIA_KINDS = {"anime": ANIME, "manga": MANGA, "libro": BOOK, "novela": BOOK}
_GENERAL = re.compile(
    r"\b(?:que\s+(?:es|son|era|fue)(?:\s+(?:un|una|el|la|los|las))?"
    r"|cuando\s+(?:nacio|murio|fue|empezo|termino|se\s+fundo|salio|se\s+creo)"
    r"|donde\s+(?:esta|queda|nacio)"
    r"|cual\s+es\s+la\s+capital\s+de"
    r"|cuantos\s+habitantes\s+tiene)\s+(?P<topic>.+)",
    re.DOTALL,
)
_DEFINE_WORDS = 3
_WORD = re.compile(r"[a-zñü]+")

log = logging.getLogger(__name__)


class InfoError(Exception):
    """No se pudo consultar la fuente."""


@dataclass(frozen=True)
class InfoQuery:
    kind: str
    topic: str = ""
    tomorrow: bool = False
    amount: float = 1.0
    target: str = ""


def _plain(text: str) -> str:
    """Sin tildes ni mayúsculas: las reglas no dependen de cómo lo escriba o transcriba la voz."""
    return normalize(text)


def _original(text: str, plain: str, match: re.Match[str], group: str) -> str:
    """El tema tal como se escribió: Wikcionario distingue "efímero" de "efimero"."""
    if len(text) != len(plain):
        return match.group(group)
    start, end = match.span(group)
    return text[start:end]


def _weather_query(text: str, plain: str) -> InfoQuery | None:
    if _WEATHER.search(plain) is None:
        return None
    match = _CITY.search(plain)
    city = ""
    if match is not None:
        noise = _CITY_NOISE.search(match.group("city"))
        city = _original(text, plain, match, "city")
        city = city[: noise.start()] if noise else city
        city = city.strip(" .'-")
    if city and clean_topic(city) is None:
        city = ""
    return InfoQuery(WEATHER, city, tomorrow="manana" in plain.split())


def _currency_query(plain: str) -> InfoQuery | None:
    match = _CONVERT.search(plain) or _CURRENCY_PRICE.search(plain)
    if match is None:
        return None
    source = CURRENCIES[match.group("source")]
    target_word = match.group("target")
    target = CURRENCIES[target_word] if target_word else ("EUR" if source == "USD" else "USD")
    if source == target:
        return None
    raw_amount = match.groupdict().get("amount")
    amount = float(raw_amount.replace(",", ".")) if raw_amount else 1.0
    return InfoQuery(CURRENCY, source, amount=amount, target=target)


def parse_info_query(text: str) -> InfoQuery | None:
    """Reconoce preguntas concretas. Lo que no encaje en ninguna regla no se busca."""
    plain = _plain(text)
    found = _weather_query(text, plain) or _currency_query(plain)
    if found is not None:
        return found
    define = _DEFINE.search(plain)
    if define is not None:
        topic = clean_topic(_original(text, plain, define, "topic"))
        if topic and len(topic.split()) <= _DEFINE_WORDS:
            return InfoQuery(DEFINE, topic)
        return None
    media = _MEDIA.search(plain)
    if media is not None:
        topic = clean_topic(_original(text, plain, media, "topic"))
        return InfoQuery(_MEDIA_KINDS[media.group("kind")], topic) if topic else None
    general = _GENERAL.search(plain)
    if general is not None:
        topic = clean_topic(_original(text, plain, general, "topic"))
        if topic and not _plain(topic).startswith("que "):
            return InfoQuery(WIKI, topic)
    return None


def _relevant(topic: str, *candidates: str) -> bool:
    """Las búsquedas devuelven parecidos: el tema tiene que estar en el título o al empezar."""
    wanted = [w for w in _WORD.findall(_plain(topic)) if len(w) > 2] or _plain(topic).split()
    for candidate in candidates:
        plain = _plain(candidate)
        words = set(_WORD.findall(plain))
        if all(w in words for w in wanted):
            return True
        if name_similarity(_plain(topic), plain) >= MIN_NAME_SIMILARITY:
            return True
    return False


def _no_data(provider: str, topic: str) -> WebResult:
    return WebResult(
        (f"{provider} no tiene datos de {topic}: di que no lo sabes con seguridad y no inventes.",),
        provider=provider,
    )


class InfoClient:
    """Peticiones con caché SQLite y un límite diario común a todas las fuentes."""

    def __init__(self, cache_path: Path, transport: httpx.BaseTransport | None = None) -> None:
        self._cache_path = cache_path
        self._transport = transport

    def get(self, kind: str, url: str, params: dict[str, Any]) -> Any:
        return self._cached(kind, f"GET {url}?{urlencode(sorted(params.items()))}",
                            lambda client: client.get(url, params=params))

    def post(self, kind: str, url: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return self._cached(kind, f"POST {url} {body}", lambda client: client.post(url, json=payload))

    def _cached(self, kind: str, key: str, send: Any) -> Any:
        try:
            with closing(sqlite3.connect(self._cache_path)) as db, db:
                self._prepare(db)
                row = db.execute(
                    "SELECT body FROM responses WHERE key = ? AND fetched_at > ?",
                    (key, time.time() - CACHE_SECONDS.get(kind, HOUR)),
                ).fetchone()
                if row is not None:
                    return json.loads(row[0])
                self._count_request(db)
            data = self._fetch(send)
            with closing(sqlite3.connect(self._cache_path)) as db, db:
                db.execute(
                    "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                    (key, json.dumps(data, ensure_ascii=False), time.time()),
                )
            return data
        except sqlite3.Error as exc:
            raise InfoError(f"Caché no disponible: {exc}") from exc

    @staticmethod
    def _prepare(db: sqlite3.Connection) -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS responses "
            "(key TEXT PRIMARY KEY, body TEXT NOT NULL, fetched_at REAL NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS requests (day TEXT PRIMARY KEY, total INTEGER NOT NULL)"
        )
        oldest = time.time() - max(CACHE_SECONDS.values())
        db.execute("DELETE FROM responses WHERE fetched_at < ?", (oldest,))

    @staticmethod
    def _count_request(db: sqlite3.Connection) -> None:
        today = date.today().isoformat()
        row = db.execute("SELECT total FROM requests WHERE day = ?", (today,)).fetchone()
        total = row[0] if row else 0
        if total >= MAX_REQUESTS_PER_DAY:
            raise InfoError("Límite diario de consultas alcanzado")
        db.execute("DELETE FROM requests WHERE day <> ?", (today,))
        db.execute("INSERT OR REPLACE INTO requests VALUES (?, ?)", (today, total + 1))

    def _fetch(self, send: Any) -> Any:
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                transport=self._transport,
            ) as client:
                response = send(client)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InfoError(str(exc)) from exc


class InfoLookup:
    def __init__(self, client: InfoClient, home_city: str = "") -> None:
        self._client = client
        self.home_city = home_city

    def search(self, query: InfoQuery) -> WebResult:
        provider = PROVIDERS[query.kind]
        handlers = {
            WIKI: self._wiki, DEFINE: self._define, WEATHER: self._weather,
            CURRENCY: self._currency, ANIME: self._media, MANGA: self._media, BOOK: self._book,
        }
        try:
            return handlers[query.kind](query)
        except (InfoError, KeyError, TypeError, ValueError, IndexError) as exc:
            log.warning("No se pudo consultar %s: %s", provider, exc)
            return WebResult(
                (f"{provider} no respondió: di que ahora no puedes comprobarlo y no inventes.",),
                failed=True,
                provider=provider,
            )

    def wiki(self, topic: str) -> WebResult:
        return self.search(InfoQuery(WIKI, topic))

    def _wiki(self, query: InfoQuery) -> WebResult:
        data = self._client.get(WIKI, WIKIPEDIA_API, {
            "action": "query", "generator": "search", "gsrsearch": query.topic,
            "gsrlimit": WIKI_RESULTS, "prop": "extracts|info|pageprops",
            "ppprop": "disambiguation", "exintro": 1, "explaintext": 1,
            "exchars": MAX_EXTRACT_CHARS, "inprop": "url", "format": "json", "formatversion": 2,
        })
        pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
        for page in pages:
            if "disambiguation" in page.get("pageprops", {}):
                continue
            title, extract = str(page.get("title", "")), str(page.get("extract", ""))
            if extract and _relevant(query.topic, title, extract[:120]):
                text = clean_text(extract, MAX_EXTRACT_CHARS)
                fact = f"Wikipedia en español, artículo «{title}»: {text}"
                return WebResult((fact,), (str(page["fullurl"]),), provider=PROVIDERS[WIKI])
        return _no_data("Wikipedia", query.topic)

    def _define(self, query: InfoQuery) -> WebResult:
        word = query.topic.strip()
        data = self._client.get(DEFINE, WIKTIONARY_API, {
            "action": "query", "prop": "extracts", "titles": word, "explaintext": 1,
            "redirects": 1, "format": "json", "formatversion": 2,
        })
        page = data["query"]["pages"][0]
        text = str(page.get("extract", ""))
        spanish = text.split("== Español ==", 1)
        if page.get("missing") or len(spanish) < 2:
            return _no_data("Wikcionario", word)
        section = re.split(r"\n== [^=]", spanish[1], maxsplit=1)[0]
        section = re.sub(r"=+\s*(Traducciones|Información adicional|Véase también)\s*=+.*", "",
                         section, flags=re.DOTALL)
        section = re.sub(r"=+\s*([^=]+?)\s*=+", r"\1:", section)
        title = str(page.get("title", word))
        fact = f"Wikcionario, «{title}»: {clean_text(section, MAX_EXTRACT_CHARS)}"
        url = f"https://es.wiktionary.org/wiki/{quote(title.replace(' ', '_'))}"
        return WebResult((fact,), (url,), provider=PROVIDERS[DEFINE])

    def _weather(self, query: InfoQuery) -> WebResult:
        city = query.topic or self.home_city
        if not city:
            return WebResult((
                "El usuario pregunta por el tiempo sin decir la ciudad: pregúntale de qué ciudad "
                "quiere saberlo y no inventes datos.",
            ))
        places = self._client.get("geocoding", GEOCODING_API, {
            "name": city, "count": 1, "language": "es", "format": "json",
        }).get("results") or []
        if not places:
            return _no_data("Open-Meteo", f"una ciudad llamada {city}")
        place = places[0]
        data = self._client.get(WEATHER, FORECAST_API, {
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 2, "timezone": "auto",
        })
        where = ", ".join(str(p) for p in (place["name"], place.get("admin1"), place.get("country")) if p)
        daily, day = data["daily"], 1 if query.tomorrow else 0
        forecast = (
            f"{'Mañana' if query.tomorrow else 'Hoy'}: {WEATHER_CODES.get(daily['weather_code'][day], 'sin dato')}, "
            f"máxima {daily['temperature_2m_max'][day]:.0f} °C, mínima {daily['temperature_2m_min'][day]:.0f} °C, "
            f"probabilidad de lluvia {daily['precipitation_probability_max'][day]} %."
        )
        now = data["current"]
        current = (
            f"Ahora: {now['temperature_2m']:.0f} °C, {WEATHER_CODES.get(now['weather_code'], 'sin dato')}, "
            f"humedad {now['relative_humidity_2m']} %, viento {now['wind_speed_10m']:.0f} km/h. "
        )
        fact = f"Open-Meteo, tiempo en {where}. {'' if query.tomorrow else current}{forecast}"
        return WebResult((fact,), ("https://open-meteo.com/",), provider=PROVIDERS[WEATHER])

    def _currency(self, query: InfoQuery) -> WebResult:
        source, target = query.topic, query.target
        data = self._client.get(CURRENCY, f"{CURRENCY_API}/{source}/{target}", {})
        rate = float(data["rate"])
        amount = query.amount
        names = CURRENCY_NAMES
        fact = (
            f"Frankfurter, tipo de cambio del {data['date']} (bancos centrales): 1 {source} = "
            f"{rate:.4f} {target}. {amount:g} {names[source]} son {amount * rate:,.2f} {names[target]}."
        )
        return WebResult((fact,), ("https://frankfurter.dev/",), provider=PROVIDERS[CURRENCY])

    def _media(self, query: InfoQuery) -> WebResult:
        kind = "ANIME" if query.kind == ANIME else "MANGA"
        data = self._client.post(query.kind, ANILIST_API, {
            "query": (
                "query ($s: String, $t: MediaType) { Media(search: $s, type: $t) { "
                "title { romaji english native } synonyms description(asHtml: false) episodes "
                "chapters status startDate { year } studios(isMain: true) { nodes { name } } "
                "staff(perPage: 2, sort: RELEVANCE) { nodes { name { full } } } genres siteUrl } }"
            ),
            "variables": {"s": query.topic, "t": kind},
        })
        media = (data.get("data") or {}).get("Media")
        if not media:
            return _no_data("AniList", query.topic)
        titles = [t for t in (media["title"].get("romaji"), media["title"].get("english"),
                              media["title"].get("native"), *media.get("synonyms", [])) if t]
        if not _relevant(query.topic, *titles):
            return _no_data("AniList", query.topic)
        label = "anime" if kind == "ANIME" else "manga"
        details = [f"AniList, {label}: {titles[0]}"]
        if media["title"].get("english") and media["title"]["english"] != titles[0]:
            details[0] += f" (en inglés, {media['title']['english']})"
        studios = [n["name"] for n in media.get("studios", {}).get("nodes", [])]
        staff = [n["name"]["full"] for n in media.get("staff", {}).get("nodes", [])]
        year = (media.get("startDate") or {}).get("year")
        for name, value in (
            ("Estudio", ", ".join(studios)), ("Autoría", ", ".join(staff) if kind == "MANGA" else ""),
            ("Año", year), ("Episodios", media.get("episodes")), ("Capítulos", media.get("chapters")),
            ("Géneros", ", ".join(media.get("genres", []))),
        ):
            if value:
                details.append(f"{name}: {value}")
        synopsis = clean_text(re.sub(r"<[^>]+>", " ", media.get("description") or ""), MAX_SYNOPSIS_CHARS)
        fact = ". ".join(details) + "."
        if synopsis:
            fact += f" Sinopsis en inglés, resúmela en español: {synopsis}"
        return WebResult((fact,), (str(media["siteUrl"]),), provider=PROVIDERS[query.kind])

    def _book(self, query: InfoQuery) -> WebResult:
        data = self._client.get(BOOK, OPENLIBRARY_API, {
            "q": query.topic, "limit": 3, "fields": "title,author_name,first_publish_year,key",
        })
        for doc in data.get("docs", []):
            if not _relevant(query.topic, str(doc.get("title", ""))):
                continue
            authors = ", ".join(doc.get("author_name", [])[:3]) or "desconocido"
            fact = f"Open Library, libro «{doc['title']}»: autor {authors}"
            if doc.get("first_publish_year"):
                fact += f", primera publicación en {doc['first_publish_year']}"
            url = f"https://openlibrary.org{doc['key']}"
            return WebResult((fact + ".",), (url,), provider=PROVIDERS[BOOK])
        return _no_data("Open Library", query.topic)
