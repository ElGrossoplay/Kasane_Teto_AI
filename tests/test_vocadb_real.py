import pytest

from kasane_teto.tools.vocadb import VocaDBClient
from kasane_teto.tools.web_lookup import MusicLookup, WebQuery, parse_query

pytestmark = pytest.mark.slow


@pytest.fixture
def lookup(tmp_path):
    return MusicLookup(VocaDBClient(tmp_path / "cache.sqlite3"))


def test_real_song_author(lookup):
    result = lookup.search(parse_query("¿Quién hizo Senbonzakura?"))
    assert "KurousaP" in result.facts[0]
    assert "2011" in result.facts[0]
    assert result.sources


def test_real_artist_top_songs(lookup):
    result = lookup.search(WebQuery("Kikuo", True, 5))
    assert result.facts[0].count("Kikuo") >= 5
    assert result.sources == ("https://vocadb.net/Ar/470",)


def test_real_voice_songs_include_every_voicebank(lookup):
    result = lookup.search(WebQuery("Kasane Teto", True, 5))
    assert "Mesmerizer" in result.facts[0]


def test_real_unknown_name_gives_no_facts(lookup):
    assert lookup.search(WebQuery("capital de Japon")).facts == ()
