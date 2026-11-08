import json
import time

import httpx
import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer

import kasane_teto.core.conversation as conversation
from kasane_teto.core.events import EventBus
from kasane_teto.memory.knowledge import Entry, KnowledgeBase
from kasane_teto.tools import info_sources
from kasane_teto.tools.info_sources import (
    ANIME,
    BOOK,
    CURRENCY,
    DEFINE,
    WEATHER,
    WIKI,
    InfoClient,
    InfoLookup,
    InfoQuery,
    parse_info_query,
)
from kasane_teto.tools.web_lookup import WebResult


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¿Qué tiempo hace en Guadalajara?", InfoQuery(WEATHER, "Guadalajara")),
        ("¿Va a llover mañana en Bogotá?", InfoQuery(WEATHER, "Bogotá", tomorrow=True)),
        ("¿Qué tiempo hace hoy?", InfoQuery(WEATHER, "")),
        ("¿Cuánto son 20 dólares en pesos mexicanos?", InfoQuery(CURRENCY, "USD", amount=20, target="MXN")),
        ("¿A cuánto está el euro?", InfoQuery(CURRENCY, "EUR", target="USD")),
        ("¿Qué significa efímero?", InfoQuery(DEFINE, "efímero")),
        ("Háblame del anime Frieren", InfoQuery(ANIME, "Frieren")),
        ("¿De quién es el libro Cien años de soledad?", InfoQuery(BOOK, "Cien años de soledad")),
        ("¿Qué es la fotosíntesis?", InfoQuery(WIKI, "fotosíntesis")),
        ("¿Cuándo nació Einstein?", InfoQuery(WIKI, "Einstein")),
        ("¿Cuál es la capital de Australia?", InfoQuery(WIKI, "Australia")),
    ],
)
def test_questions_are_recognised(text, expected):
    assert parse_info_query(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Hola, ¿qué tal?",
        "¿Qué es lo que más te gusta?",
        "¿Qué es eso?",
        "Hace mucho tiempo que no hablamos",
        "¿Qué significa mi nombre para ti?",
        "¿Qué es tu número 123456789?",
        "¿Cuánto tiempo llevas despierta?",
    ],
)
def test_chat_and_personal_things_are_not_searched(text):
    assert parse_info_query(text) is None


def test_weather_city_without_trailing_words():
    assert parse_info_query("qué tiempo hace en Madrid esta tarde").topic == "Madrid"


class Api:
    """Respuestas reducidas con la forma real de cada API, medida el 2026-11-08."""

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "es.wikipedia.org":
            return httpx.Response(200, json={"query": {"pages": [
                {"index": 1, "title": "Desambiguación", "pageprops": {"disambiguation": ""},
                 "extract": "Puede referirse a…", "fullurl": "x"},
                {"index": 2, "title": "Lionel Messi", "extract": "Lionel Andrés Messi es un futbolista argentino.",
                 "fullurl": "https://es.wikipedia.org/wiki/Lionel_Messi"},
            ]}})
        if host == "es.wiktionary.org":
            return httpx.Response(200, json={"query": {"pages": [{"title": "efímero", "extract": (
                "== Español ==\n=== Etimología 1 ===\nDel griego.\n==== Adjetivo ====\n1\nQue dura un día."
                "\n==== Traducciones ====\nephemeral\n== Referencias ==")}]}})
        if host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"name": "Guadalajara", "latitude": 20.6,
                "longitude": -103.3, "admin1": "Jalisco", "country": "México"}]})
        if host == "api.open-meteo.com":
            return httpx.Response(200, json={
                "current": {"temperature_2m": 20.2, "relative_humidity_2m": 62, "weather_code": 0,
                            "wind_speed_10m": 7.8},
                "daily": {"weather_code": [1, 61], "temperature_2m_max": [27.6, 25.0],
                          "temperature_2m_min": [15.0, 14.0], "precipitation_probability_max": [20, 80]},
            })
        if host == "api.frankfurter.dev":
            assert path == "/v2/rate/USD/MXN"
            return httpx.Response(200, json={"date": "2026-11-08", "base": "USD", "quote": "MXN", "rate": 18.66})
        if host == "graphql.anilist.co":
            return httpx.Response(200, json={"data": {"Media": {
                "title": {"romaji": "Sousou no Frieren", "english": "Frieren: Beyond Journey's End",
                          "native": "葬送のフリーレン"},
                "synonyms": ["Frieren"], "description": "An elf mage<br>outlives her party.",
                "episodes": 28, "chapters": None, "status": "FINISHED", "startDate": {"year": 2023},
                "studios": {"nodes": [{"name": "Madhouse"}]}, "staff": {"nodes": []},
                "genres": ["Adventure", "Drama"], "siteUrl": "https://anilist.co/anime/154587",
            }}})
        if host == "openlibrary.org":
            return httpx.Response(200, json={"docs": [{"title": "Cien años de soledad",
                "author_name": ["Gabriel García Márquez"], "first_publish_year": 1967, "key": "/works/OL274505W"}]})
        return httpx.Response(404)


@pytest.fixture
def lookup(tmp_path):
    api = Api()
    return InfoLookup(InfoClient(tmp_path / "info.sqlite3", httpx.MockTransport(api))), api


def test_wikipedia_skips_disambiguation_and_cites_the_article(lookup):
    info, _ = lookup
    result = info.search(InfoQuery(WIKI, "Messi"))
    assert "futbolista argentino" in result.facts[0]
    assert result.sources == ("https://es.wikipedia.org/wiki/Lionel_Messi",)
    assert result.provider.startswith("Wikipedia")


def test_unrelated_wikipedia_result_is_not_used(lookup):
    info, _ = lookup
    result = info.search(InfoQuery(WIKI, "Fulanito Pérez"))
    assert not result.sources
    assert "no inventes" in result.facts[0]


def test_wiktionary_keeps_only_the_spanish_meaning(lookup):
    info, _ = lookup
    result = info.search(InfoQuery(DEFINE, "efímero"))
    assert "Que dura un día." in result.facts[0]
    assert "ephemeral" not in result.facts[0]
    assert result.sources == ("https://es.wiktionary.org/wiki/ef%C3%ADmero",)


def test_weather_today_and_tomorrow(lookup):
    info, _ = lookup
    today = info.search(InfoQuery(WEATHER, "Guadalajara"))
    assert "20 °C" in today.facts[0] and "despejado" in today.facts[0] and "Jalisco" in today.facts[0]
    tomorrow = info.search(InfoQuery(WEATHER, "Guadalajara", tomorrow=True))
    assert "Mañana: lluvia débil" in tomorrow.facts[0]
    assert "Ahora" not in tomorrow.facts[0]


def test_weather_without_city_asks_and_sends_nothing(lookup):
    info, api = lookup
    result = info.search(InfoQuery(WEATHER, ""))
    assert "pregúntale" in result.facts[0]
    assert api.requests == []


def test_weather_uses_the_saved_city(lookup):
    info, api = lookup
    info.home_city = "Guadalajara"
    info.search(InfoQuery(WEATHER, ""))
    assert api.requests[0].url.params["name"] == "Guadalajara"


def test_currency_conversion(lookup):
    info, _ = lookup
    result = info.search(InfoQuery(CURRENCY, "USD", amount=20, target="MXN"))
    assert "20 dólares estadounidenses son 373.20 pesos mexicanos" in result.facts[0]


def test_anime_details_and_spanish_summary_request(lookup):
    info, api = lookup
    result = info.search(InfoQuery(ANIME, "Frieren"))
    assert "Madhouse" in result.facts[0] and "Episodios: 28" in result.facts[0]
    assert "<br>" not in result.facts[0]
    assert json.loads(api.requests[0].content)["variables"] == {"s": "Frieren", "t": "ANIME"}


def test_book_author(lookup):
    info, _ = lookup
    result = info.search(InfoQuery(BOOK, "Cien años de soledad"))
    assert "Gabriel García Márquez" in result.facts[0] and "1967" in result.facts[0]


def test_answers_are_cached(lookup):
    info, api = lookup
    info.search(InfoQuery(WIKI, "Messi"))
    info.search(InfoQuery(WIKI, "Messi"))
    assert len(api.requests) == 1


def test_failure_is_reported_without_crashing(tmp_path):
    broken = httpx.MockTransport(lambda request: httpx.Response(500))
    result = InfoLookup(InfoClient(tmp_path / "i.sqlite3", broken)).search(InfoQuery(WIKI, "Messi"))
    assert result.failed and "no inventes" in result.facts[0]


def test_daily_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(info_sources, "MAX_REQUESTS_PER_DAY", 1)
    info = InfoLookup(InfoClient(tmp_path / "i.sqlite3", httpx.MockTransport(Api())))
    assert not info.search(InfoQuery(WIKI, "Messi")).failed
    assert info.search(InfoQuery(BOOK, "Cien años de soledad")).failed


def test_user_agent_identifies_the_app_without_personal_data(lookup):
    info, api = lookup
    info.search(InfoQuery(WIKI, "Messi"))
    agent = api.requests[0].headers["User-Agent"]
    assert "KasaneTetoAI" in agent and "@" not in agent


# Integración con la conversación.


def install_client(monkeypatch):
    seen = []

    class FakeClient:
        finish_reason = "stop"

        def __init__(self, base_url, api_key):
            pass

        def stream_chat(self, messages, params, cancel):
            seen.append(messages)
            yield "[neutral] Vale."

    monkeypatch.setattr(conversation, "LLMClient", FakeClient)
    return seen


class FakeResources:
    game_mode = False

    def ensure_loaded(self):
        return type("Process", (), {"base_url": "http://fake", "api_key": "k"})()

    def set_busy(self, busy):
        pass

    def take_cpu_notice(self):
        return False


class FakeMusic:
    def __init__(self, result):
        self.result = result
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.result


class FakeInfo:
    home_city = ""

    def __init__(self, result=None):
        self.queries = []
        self.result = result or WebResult(
            ("Wikipedia en español, artículo «Lionel Messi»: futbolista.",),
            ("https://es.wikipedia.org/wiki/Lionel_Messi",),
            provider="Wikipedia (CC BY-SA 4.0)",
        )

    def search(self, query):
        self.queries.append(query)
        return self.result

    def wiki(self, topic):
        return self.search(InfoQuery(WIKI, topic))


def pump(condition, timeout_ms=3000):
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert condition()


@pytest.fixture
def chat(qapp, settings, monkeypatch):
    services = []

    def make(music_result=WebResult(("VocaDB no conoce Messi.",)), web=True, general=True):
        seen = install_client(monkeypatch)
        settings.set("web.enabled", web)
        settings.set("web.general", general)
        bus = EventBus()
        record = {"done": 0, "notices": [], "status": []}
        bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
        bus.assistant_notice.connect(record["notices"].append)
        bus.assistant_status.connect(record["status"].append)
        music, info = FakeMusic(music_result), FakeInfo()
        knowledge = KnowledgeBase([Entry("miku", ("miku",), "Dato de Miku.", "")])
        services.append(conversation.ConversationService(
            bus, FakeResources(), settings, knowledge, music, info=info
        ))
        return bus, music, info, seen, record

    return make


def test_general_search_is_off_by_default(settings):
    assert settings.get("web.general") is False


def test_unknown_to_vocadb_falls_back_to_wikipedia(chat):
    bus, music, info, seen, record = chat()
    bus.user_message.emit("¿Quién es Messi?")
    pump(lambda: record["done"] == 1)
    assert [q.topic for q in music.queries] == ["Messi"]
    assert [q.topic for q in info.queries] == ["Messi"]
    assert "futbolista" in seen[0][-1]["content"]
    assert "Datos de Wikipedia (CC BY-SA 4.0): https://es.wikipedia.org/wiki/Lionel_Messi" in record["notices"][0]
    assert "Buscando en VocaDB y Wikipedia…" in record["status"]


def test_vocadb_down_still_uses_wikipedia(chat):
    bus, _, info, seen, record = chat(WebResult(("VocaDB no respondió.",), failed=True))
    bus.user_message.emit("¿Quién es Messi?")
    pump(lambda: record["done"] == 1)
    assert [q.topic for q in info.queries] == ["Messi"]
    assert "futbolista" in seen[0][-1]["content"]
    assert "VocaDB no respondió. Datos de Wikipedia" in record["notices"][0]


def test_known_to_vocadb_does_not_use_wikipedia(chat):
    found = WebResult(("VocaDB, artista: Kikuo.",), ("https://vocadb.net/Ar/470",))
    bus, _, info, _, record = chat(found)
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    assert info.queries == []


def test_general_search_off_sends_nothing_and_says_so(chat):
    bus, _, info, _, record = chat(web=False, general=False)
    bus.user_message.emit("¿Qué es la fotosíntesis?")
    pump(lambda: record["done"] == 1)
    assert info.queries == []
    assert record["notices"] == [conversation.GENERAL_OFF_NOTICE]


def test_weather_goes_straight_to_its_source(chat):
    bus, music, info, _, record = chat()
    bus.user_message.emit("¿Qué tiempo hace en Madrid?")
    pump(lambda: record["done"] == 1)
    assert music.queries == []
    assert info.queries == [InfoQuery(WEATHER, "Madrid")]
    assert "Buscando en Open-Meteo.com…" in record["status"]


def test_wikipedia_alone_when_music_search_is_off(chat):
    bus, music, info, _, record = chat(web=False)
    bus.user_message.emit("¿Quién es Messi?")
    pump(lambda: record["done"] == 1)
    assert music.queries == []
    assert [q.topic for q in info.queries] == ["Messi"]


def test_local_card_wins_over_wikipedia(chat):
    bus, _, info, _, record = chat()
    bus.user_message.emit("¿Qué es Miku?")
    pump(lambda: record["done"] == 1)
    assert info.queries == []


def test_memories_never_reach_the_search(chat):
    bus, _, info, _, record = chat()
    bus.user_message.emit("¿Qué es mi perro para ti?")
    pump(lambda: record["done"] == 1)
    assert info.queries == []
