import pytest

from kasane_teto.memory.knowledge import Entry, KnowledgeBase
from kasane_teto.voice.transcript import fix_question, fix_transcript


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("Kienes Katsune Miku.", "¿Quién es Katsune Miku?"),
        ("Kienes Kiku", "¿Quién es Kiku?"),
        ("Dime kienes kikuo.", "¿Quién es kikuo?"),
        ("Quienes Kikuu.", "¿Quién es Kikuu?"),
        ("Gen es Kikuho.", "¿Quién es Kikuho?"),
        ("Quien es Mili", "¿Quién es Mili?"),
        ("¿Quién es Mili?", "¿Quién es Mili?"),
    ],
)
def test_who_is_is_rewritten(heard, expected):
    assert fix_question(heard) == expected


@pytest.mark.parametrize(
    "text",
    [
        "¿Quién hizo Senbonzakura?",
        "Quienes son YOASOBI",
        "Gen es un nombre corto.",
        "Hoy tuve un día bastante pesado.",
        "¿Qué me recomiendas hacer esta noche?",
    ],
)
def test_other_sentences_stay_the_same(text):
    assert fix_question(text) == text


def test_misspelled_word_inside_a_sentence():
    assert fix_question("No sé kien es") == "No sé quién es"


@pytest.fixture
def base():
    return KnowledgeBase(
        [
            Entry("miku", ("Hatsune Miku", "Miku"), "h", ""),
            Entry("rin", ("Kagamine Rin",), "h", ""),
            Entry("ia", ("Cantante IA",), "h", ""),
            Entry("sen", ("Senbonzakura",), "h", ""),
            Entry("vo", ("Vocaloid",), "h", ""),
        ]
    )


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("¿Quién es Katsune Miku?", "¿Quién es Hatsune Miku?"),
        ("Háblame de Senbonsakura, por favor", "Háblame de Senbonzakura, por favor"),
        ("Háblame sobre Vocaloid.", "Háblame sobre Vocaloid."),
        ("¿Qué opinas de Kagamine Rin y Len?", "¿Qué opinas de Kagamine Rin y Len?"),
    ],
)
def test_close_names_are_fixed(base, heard, expected):
    assert base.correct_names(heard) == expected


@pytest.mark.parametrize(
    "text",
    [
        "¿Quién es esa cantante?",
        "Esas cantantes son buenas",
        "Hoy tuve un día bastante pesado en el trabajo.",
        "Explícame qué es la memoria RAM.",
        "¿Qué me recomiendas hacer esta noche?",
        "Vamos a caminar un rato",
        "Dime cinco canciones de Mitchie M.",
        "¿Cuál es la canción más famosa?",
    ],
)
def test_ordinary_sentences_are_not_touched(base, text):
    assert base.correct_names(text) == text


def test_both_fixes_work_together(base):
    assert fix_transcript("Kienes Katsune Miku.", base.correct_names) == "¿Quién es Hatsune Miku?"
