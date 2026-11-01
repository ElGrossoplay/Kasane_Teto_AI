import pytest

from kasane_teto.character.states import PetState
from kasane_teto.personality.emotion_parser import EmotionParser
from kasane_teto.personality.prompt_builder import (
    build_messages,
    estimate_tokens,
    load_system_prompt,
)


def parse(chunks):
    parser = EmotionParser()
    text = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
    return text, parser.emotion


def test_tag_in_one_chunk():
    assert parse(["[feliz] ¡Hola!"]) == ("¡Hola!", PetState.HAPPY)


def test_tag_split_across_chunks():
    assert parse(["[", "fel", "iz", "]", " ", "¡Ho", "la!"]) == ("¡Hola!", PetState.HAPPY)


def test_leading_whitespace_is_ignored():
    assert parse(["\n ", "[enfadada] Grr"]) == ("Grr", PetState.ANGRY)


def test_no_tag_keeps_text():
    assert parse(["Hola ", "mundo"]) == ("Hola mundo", None)


def test_unknown_tag_is_hidden():
    assert parse(["[bailando] Hola"]) == ("Hola", None)


def test_uppercase_tag_is_accepted():
    assert parse(["[FELIZ] Hola"]) == ("Hola", PetState.HAPPY)


def test_long_bracket_text_is_not_a_tag():
    text = "[esto es un texto largo sin cerrar"
    assert parse([text]) == (text, None)


def test_only_tag_in_stream():
    assert parse(["[aburrida]"]) == ("", PetState.BORED)


def test_later_brackets_stay_in_text():
    assert parse(["[neutral] Mira [esto]"]) == ("Mira [esto]", PetState.SPEAKING)


def test_system_prompt_stays_free_of_her_biography():
    prompt = load_system_prompt()
    for word in ("Mesmerizer", "2channel", "quimera"):
        assert word not in prompt


def test_system_prompt_lists_every_emotion():
    prompt = load_system_prompt()
    for tag in ("neutral", "feliz", "sorprendida", "confundida", "enfadada", "aburrida"):
        assert f"[{tag}]" in prompt


def user(text):
    return {"role": "user", "content": text}


def assistant(text):
    return {"role": "assistant", "content": text}


def test_system_prompt_goes_first():
    messages = build_messages("sistema", [user("hola")], 4096, 200)
    assert messages == [{"role": "system", "content": "sistema"}, user("hola")]


def test_old_turns_are_dropped_when_context_is_full():
    history = [user("a" * 300), assistant("b" * 300), user("c" * 300), assistant("d"), user("e")]
    messages = build_messages("s", history, 180, 20)
    assert messages[-1] == user("e")
    assert user("a" * 300) not in messages


def test_history_always_starts_with_user_turn():
    history = [user("a" * 300), assistant("b" * 30), user("c")]
    messages = build_messages("s", history, 70, 20)
    assert messages[1]["role"] == "user"


def test_latest_message_is_kept_even_if_huge():
    messages = build_messages("s", [user("x" * 10_000)], 100, 20)
    assert messages[-1]["content"] == "x" * 10_000


@pytest.mark.parametrize("text", ["", "hola", "x" * 100])
def test_estimate_is_positive(text):
    assert estimate_tokens(text) > 0
