import pytest

from kasane_teto.core.paths import knowledge_root
from kasane_teto.memory.knowledge import (
    Entry,
    KnowledgeBase,
    KnowledgeError,
    is_follow_up,
    normalize,
    wants_opinion,
)
from kasane_teto.personality.prompt_builder import estimate_tokens, knowledge_block


@pytest.fixture(scope="module")
def base():
    return KnowledgeBase.load(knowledge_root())


def ids(entries):
    return [entry.id for entry in entries]


def test_real_file_loads_with_unique_ids(base):
    assert len(base) >= 40


def test_normalize_removes_accents_and_keeps_japanese():
    assert normalize("Ichiká ÑO") == "ichika no"
    assert normalize("初音ミク") == "初音ミク"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¿Quién es Hatsune Miku?", "miku"),
        ("háblame de MIKU", "miku"),
        ("初音ミクって誰", "miku"),
        ("qué es UTAU", "utau"),
        ("¿Rin y Len son gemelos?", "rin_len"),
        ("quien hizo Ghost Rule", "ghost_rule"),
        ("me gusta DECO*27", "deco27"),
        ("conoces a n-buna", "nbuna"),
    ],
)
def test_names_find_their_entry(base, text, expected):
    assert expected in ids(base.search(text))


def test_most_recently_named_order_follows_the_text(base):
    assert ids(base.search("Compara a Luka con Miku")) == ["luka", "miku"]


def test_results_are_limited(base):
    assert len(base.search("Miku, Rin, Luka, MEIKO, KAITO y GUMI")) == 3


@pytest.mark.parametrize(
    "text",
    [
        "¿Qué opinas de la IA?",
        "La inteligencia artificial me da miedo",
        "Lena fue a la tienda",
        "¿Qué tiempo hace hoy?",
        "Cuéntame un chiste",
        "¿Cuál es tu canción favorita?",
    ],
)
def test_unrelated_text_activates_nothing(base, text):
    assert base.search(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "¿Y cuándo salió?",
        "¿Y qué sientes por ella?",
        "¿Qué canciones tiene?",
        "¿Cuándo salió?",
        "¿Qué opinas?",
        "¿Dónde nació?",
    ],
)
def test_follow_up_questions_are_detected(text):
    assert is_follow_up(text)


@pytest.mark.parametrize(
    "text",
    [
        "Cuéntame un chiste corto.",
        "¿Qué tiempo hace hoy?",
        "¿Cuál es la capital de Japón?",
        "Explícame qué es la memoria RAM del ordenador.",
    ],
)
def test_new_topics_are_not_follow_ups(text):
    assert not is_follow_up(text)


@pytest.mark.parametrize(
    "text", ["¿Qué opinas de Miku?", "¿Te cae bien Luka?", "¿Te llevas bien con Rin?", "¿Cuál es tu favorita?"]
)
def test_opinion_questions_are_detected(text):
    assert wants_opinion(text)


@pytest.mark.parametrize("text", ["¿Quién es Hatsune Miku?", "Háblame de Vocaloid", "¿Cuándo salió?"])
def test_factual_questions_are_not_opinions(text):
    assert not wants_opinion(text)


def test_block_can_omit_feelings():
    block = knowledge_block([Entry("a", ("N",), "Hecho.", "Opinión.")], include_feelings=False)
    assert "Opinión." not in block


@pytest.mark.parametrize(
    "text", ["¿Quién eres?", "¿Cuántos años tienes?", "¿Cuáles son tus canciones?", "¿Quién es Kasane Teto?"]
)
def test_questions_about_her_use_her_entry(base, text):
    assert "teto" in ids(base.search(text))


@pytest.mark.parametrize("text", ["¡Hola Teto!", "Teto, cuéntame un chiste", "¿Qué tal, Teto?"])
def test_saying_her_name_does_not_load_her_entry(base, text):
    assert "teto" not in ids(base.search(text))


def test_real_vocabulary_uses_proper_capitals(base):
    words = base.vocabulary(max_chars=2000)
    for name in ("Hatsune Miku", "UTAU", "Kagamine Rin", "DECO*27"):
        assert name in words


def test_singer_ia_needs_a_specific_name(base):
    assert ids(base.search("¿Conoces a la cantante IA?")) == ["ia"]


def test_keywords_find_entry_without_a_name(base):
    assert "luka" in ids(base.search("¿quién fue la primera bilingüe?"))


def test_quotes_in_text_do_not_break_search(base):
    assert base.search('que significa "kafkiano" OR (x') == []


def test_duplicate_ids_are_rejected():
    entry = Entry("a", ("a",), "h", "")
    with pytest.raises(KnowledgeError):
        KnowledgeBase([entry, entry])


def test_incomplete_entry_is_rejected(tmp_path):
    (tmp_path / "x.toml").write_text('[[ficha]]\nid = "a"\n', encoding="utf-8")
    with pytest.raises(KnowledgeError):
        KnowledgeBase.load(tmp_path)


def test_broken_file_is_rejected(tmp_path):
    (tmp_path / "x.toml").write_text("esto no = = toml", encoding="utf-8")
    with pytest.raises(KnowledgeError):
        KnowledgeBase.load(tmp_path)


def test_empty_folder_gives_empty_base(tmp_path):
    base = KnowledgeBase.load(tmp_path)
    assert len(base) == 0
    assert base.search("Miku") == []


def test_block_labels_reaction_as_feeling():
    block = knowledge_block([Entry("a", ("Nombre",), "Hecho.", "Opinión.")])
    assert "Hechos: Hecho." in block
    assert "Lo que sientes tú: Opinión." in block


def test_block_is_empty_without_entries():
    assert knowledge_block([]) == ""


def test_three_largest_entries_fit_the_context(base):
    entries = sorted(base._entries.values(), key=lambda e: len(e.facts) + len(e.reaction))[-3:]
    assert estimate_tokens(knowledge_block(entries)) < 700
