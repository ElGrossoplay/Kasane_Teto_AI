"""Consultas reales a las fuentes de información general. Necesitan Internet: `pytest -m slow`."""

import pytest

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
)

pytestmark = pytest.mark.slow


@pytest.fixture
def info(tmp_path):
    return InfoLookup(InfoClient(tmp_path / "info.sqlite3"))


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (InfoQuery(WIKI, "Messi"), "futbolista"),
        (InfoQuery(WIKI, "fotosíntesis"), "luz"),
        (InfoQuery(DEFINE, "efímero"), "dura"),
        (InfoQuery(WEATHER, "Madrid"), "°C"),
        (InfoQuery(CURRENCY, "USD", target="EUR"), "1 USD ="),
        (InfoQuery(ANIME, "Frieren"), "Madhouse"),
        (InfoQuery(BOOK, "Cien años de soledad"), "García Márquez"),
    ],
)
def test_real_sources_answer(info, query, expected):
    result = info.search(query)
    assert not result.failed, result.facts
    assert expected.casefold() in result.facts[0].casefold(), result.facts[0]
    assert result.sources
