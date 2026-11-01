import json
import sqlite3

import httpx
import pytest

from kasane_teto.tools import vocadb
from kasane_teto.tools.vocadb import VocaDBClient, VocaDBError, clean_text
from kasane_teto.tools.web_lookup import UNAVAILABLE_FACT, MusicLookup, WebQuery, parse_query

KIKUO = {
    "id": 470,
    "name": "Kikuo",
    "additionalNames": "きくお, kikk",
    "artistType": "Producer",
    "description": "Producer who started with [Vocaloid](https://example.com) **in 2010** in Japan, then kept on.",
}
SIMILAR = {"id": 829, "name": "Kikuo Sound Works", "artistType": "Circle"}
SONG = {
    "id": 8394,
    "name": "Senbonzakura",
    "additionalNames": "千本桜, A Thousand Cherry Blossoms",
    "artistString": "KurousaP feat. Hatsune Miku",
    "publishDate": "2011-09-17T00:00:00Z",
}


class FakeApi:
    def __init__(self, artists=(), songs=(), status=200, bases=None):
        self.artists = list(artists)
        self.songs = list(songs)
        self.status = status
        self.bases = bases or {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        last = request.url.path.rsplit("/", 1)[-1]
        if last.isdigit():
            base = self.bases.get(int(last))
            return httpx.Response(self.status, json={"baseVoicebank": base} if base else {})
        items = self.artists if last == "artists" else self.songs
        return httpx.Response(self.status, json={"items": items})


def client(tmp_path, api):
    return VocaDBClient(tmp_path / "cache.sqlite3", httpx.MockTransport(api))


@pytest.mark.parametrize(
    ("text", "topic", "wants_songs", "count"),
    [
        ("Dime 20 canciones de Kasane Teto", "Kasane Teto", True, 20),
        ("nombra veinte canciones de Kikuo por favor", "Kikuo", True, 20),
        ("¿Qué canciones tiene Kikuo?", "Kikuo", True, 10),
        ("¿Cuál es la canción más famosa de DECO*27?", "DECO*27", True, 10),
        ("dame 99 temas de wowaka", "wowaka", True, 20),
        ("¿Quién es Kikuo?", "Kikuo", False, 10),
        ("quien hizo la cancion Senbonzakura", "Senbonzakura", False, 10),
        ("¿Quién hizo la canción de Mesmerizer?", "Mesmerizer", False, 10),
        ("Háblame sobre el productor Mitchie M", "Mitchie M", False, 10),
        ("¿Conoces a Solaria?", "Solaria", False, 10),
        ('¿Qué sabes de "Rollin\' Girl", la de wowaka?', "Rollin' Girl", False, 10),
        ("busca en internet Tetoris", "Tetoris", False, 10),
    ],
)
def test_parse_query_keeps_only_the_name(text, topic, wants_songs, count):
    assert parse_query(text) == WebQuery(topic, wants_songs, count)


@pytest.mark.parametrize(
    "text",
    [
        "Hola, ¿cómo estás?",
        "Estoy cansado, hoy el trabajo fue horrible.",
        "¿Qué tiempo hace?",
        "Explícame qué es la memoria RAM.",
        "Háblame de mi novia Laura",
        "¿Quién es mi jefe?",
        "¿Conoces a mis padres?",
        "¿Quién es ella?",
        "Busca ana@correo.com",
        "Busca el 600123456",
        "háblame de una historia muy larga que tiene más de seis palabras seguidas",
    ],
)
def test_parse_query_ignores_personal_and_unrelated_messages(text):
    assert parse_query(text) is None


def test_clean_text_removes_links_and_marks():
    assert clean_text("See [his site](https://x.y) **now** https://a.b", 100) == "See his site now"


def test_clean_text_cuts_on_a_word():
    assert clean_text("una frase bastante larga", 12) == "una frase…"


def test_artist_search_ignores_similar_names(tmp_path):
    api = FakeApi([SIMILAR, KIKUO])
    found = client(tmp_path, api).find_artists("きくお")
    assert [artist.name for artist in found] == ["Kikuo"]
    assert found[0].url == "https://vocadb.net/Ar/470"


def test_request_identifies_the_app_and_sends_only_the_name(tmp_path):
    api = FakeApi([KIKUO])
    client(tmp_path, api).find_artists("Kikuo")
    request = api.requests[0]
    assert request.headers["user-agent"] == vocadb.USER_AGENT
    assert request.url.params["query"] == "Kikuo"
    assert request.url.host == "vocadb.net"


def test_answers_are_cached_between_clients(tmp_path):
    api = FakeApi([KIKUO])
    client(tmp_path, api).find_artists("Kikuo")
    client(tmp_path, api).find_artists("Kikuo")
    assert len(api.requests) == 1


def test_expired_cache_is_asked_again(tmp_path, monkeypatch):
    api = FakeApi([KIKUO])
    db = client(tmp_path, api)
    db.find_artists("Kikuo")
    monkeypatch.setattr(vocadb, "CACHE_SECONDS", -1)
    db.find_artists("Kikuo")
    assert len(api.requests) == 2


def test_daily_limit_stops_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(vocadb, "MAX_REQUESTS_PER_DAY", 1)
    api = FakeApi([KIKUO])
    db = client(tmp_path, api)
    db.find_artists("Kikuo")
    with pytest.raises(VocaDBError):
        db.find_artists("otro")
    assert len(api.requests) == 1


@pytest.mark.parametrize("api", [FakeApi(status=503)])
def test_http_error_is_reported_as_failure(tmp_path, api):
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Kikuo"))
    assert result.failed
    assert not result.sources


def test_network_failure_is_reported_as_failure(tmp_path):
    def broken(request):
        raise httpx.ConnectError("sin red")

    result = MusicLookup(client(tmp_path, broken)).search(WebQuery("Kikuo"))
    assert result.failed


def test_unreadable_cache_is_reported_as_failure(tmp_path):
    db_path = tmp_path / "cache.sqlite3"
    db_path.write_bytes(b"esto no es una base de datos" * 100)
    result = MusicLookup(VocaDBClient(db_path, httpx.MockTransport(FakeApi()))).search(
        WebQuery("Kikuo")
    )
    assert result.failed


def test_invalid_json_is_reported_as_failure(tmp_path):
    def bad(request):
        return httpx.Response(200, text="<html>")

    assert MusicLookup(client(tmp_path, bad)).search(WebQuery("Kikuo")).failed


def test_artist_songs_are_listed_with_source(tmp_path):
    api = FakeApi([KIKUO], [SONG])
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Kikuo", True, 3))
    assert '"Senbonzakura" (KurousaP, 2011)' in result.facts[0]
    assert "no es la lista completa" in result.facts[0]
    assert result.sources == ("https://vocadb.net/Ar/470",)
    assert api.requests[-1].url.params["maxResults"] == "3"


def test_producer_songs_skip_voicebank_search(tmp_path):
    api = FakeApi([KIKUO], [SONG])
    MusicLookup(client(tmp_path, api)).search(WebQuery("Kikuo", True, 3))
    assert "childVoicebanks" not in api.requests[-1].url.params
    assert api.requests[-1].url.params["artistId[]"] == "470"


def test_voice_songs_start_from_the_root_voicebank(tmp_path):
    teto = {"id": 116, "name": "Kasane Teto", "artistType": "UTAU"}
    api = FakeApi([teto], [SONG], bases={116: {"id": 140308}})
    MusicLookup(client(tmp_path, api)).search(WebQuery("Kasane Teto", True, 20))
    assert api.requests[-1].url.params["artistId[]"] == "140308"
    assert api.requests[-1].url.params["childVoicebanks"] == "true"


def test_voicebank_loop_in_the_data_ends(tmp_path):
    teto = {"id": 116, "name": "Kasane Teto", "artistType": "UTAU"}
    api = FakeApi([teto], [SONG], bases={116: {"id": 117}, 117: {"id": 116}})
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Kasane Teto", True))
    assert result.facts


def test_various_artists_is_translated(tmp_path):
    song = {**SONG, "artistString": "Various artists"}
    result = MusicLookup(client(tmp_path, FakeApi([KIKUO], [song]))).search(
        WebQuery("Kikuo", True)
    )
    assert "(varios artistas, 2011)" in result.facts[0]


def test_song_details_split_producer_and_voice(tmp_path):
    api = FakeApi([], [SONG])
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("千本桜"))
    assert result.facts == (
        'VocaDB, canción: "Senbonzakura". Productor: KurousaP. Voz: Hatsune Miku. '
        "Publicada en 2011.",
    )
    assert result.sources == ("https://vocadb.net/S/8394",)


def test_artist_details_translate_kind_and_clean_description(tmp_path):
    api = FakeApi([KIKUO], [])
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Kikuo"))
    assert "Tipo: productor." in result.facts[0]
    assert "Producer who started with Vocaloid in 2010 in Japan, then kept on." in result.facts[0]
    assert "example.com" not in result.facts[0]


@pytest.mark.parametrize(
    "description",
    [
        "+ Karaokes and acapellas of most of the songs can be found on [his website](https://x.y).",
        "**NOTE: This entry indicates that the voicebank was used, but gives no information.**",
        "Main illustration by Ne-ru.",
    ],
)
def test_editor_notes_are_not_treated_as_biography(tmp_path, description):
    api = FakeApi([{**KIKUO, "description": description}], [])
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Kikuo"))
    assert "Descripción" not in result.facts[0]


def test_list_without_data_tells_the_model_not_to_invent(tmp_path):
    result = MusicLookup(client(tmp_path, FakeApi())).search(WebQuery("Tanuki-P", True))
    assert "no inventes títulos" in result.facts[0]
    assert result.sources == ()
    assert not result.failed


def test_failure_is_not_presented_as_missing_data(tmp_path):
    api = FakeApi(status=503)
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Tanuki-P", True))
    assert result.failed
    assert result.facts == (UNAVAILABLE_FACT,)
    assert not result.sources


def test_unknown_name_gives_no_facts(tmp_path):
    api = FakeApi([SIMILAR], [])
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Kikuo"))
    assert result.facts == ()
    assert not result.failed


def test_song_request_for_a_title_falls_back_to_the_song(tmp_path):
    api = FakeApi([], [SONG])
    result = MusicLookup(client(tmp_path, api)).search(WebQuery("Senbonzakura", True))
    assert result.facts[0].startswith('VocaDB, canción: "Senbonzakura"')


def test_cache_keeps_responses_as_json(tmp_path):
    client(tmp_path, FakeApi([KIKUO])).find_artists("Kikuo")
    with sqlite3.connect(tmp_path / "cache.sqlite3") as db:
        body = db.execute("SELECT body FROM responses").fetchone()[0]
    assert json.loads(body)["items"][0]["id"] == 470
