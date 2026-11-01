import time

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer

import kasane_teto.core.conversation as conversation
from kasane_teto.ai.llm_client import LLMRequestError
from kasane_teto.ai.llm_process import LLMStartError
from kasane_teto.character.states import PetState
from kasane_teto.core.events import EventBus
from kasane_teto.core.resource_manager import AiProfile, choose_profiles
from kasane_teto.memory.knowledge import Entry, KnowledgeBase
from kasane_teto.tools.web_lookup import WebResult


class FakeProcess:
    base_url = "http://fake"
    api_key = "k"


class FakeResources:
    def __init__(self, error=None):
        self.error = error
        self.busy_calls = []

    def ensure_loaded(self):
        if self.error:
            raise self.error
        return FakeProcess()

    def set_busy(self, busy):
        self.busy_calls.append(busy)


def install_client(monkeypatch, chunks=(), error=None, pause=0.0, finish="stop"):
    seen = []

    class FakeClient:
        def __init__(self, base_url, api_key):
            self.finish_reason = None

        def stream_chat(self, messages, params, cancel):
            seen.append(messages)
            for chunk in chunks:
                if cancel.is_set():
                    return
                time.sleep(pause)
                yield chunk
            if error:
                raise error
            self.finish_reason = finish

    monkeypatch.setattr(conversation, "LLMClient", FakeClient)
    return seen


def pump(condition, timeout_ms=3000):
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert condition()


@pytest.fixture
def harness(qapp, settings):
    services = []

    def make(resources=None):
        bus = EventBus()
        record = {"tokens": [], "states": [], "done": 0, "errors": [], "notices": []}
        bus.assistant_token.connect(record["tokens"].append)
        bus.assistant_notice.connect(record["notices"].append)
        bus.pet_state_requested.connect(record["states"].append)
        bus.assistant_error.connect(record["errors"].append)
        bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
        resources = resources or FakeResources()
        knowledge = KnowledgeBase([Entry("miku", ("miku",), "Dato de Miku.", "")])
        service = conversation.ConversationService(bus, resources, settings, knowledge)
        services.append(service)
        return bus, service, resources, record

    return make


def test_turn_streams_text_and_applies_emotion(harness, monkeypatch):
    install_client(monkeypatch, ["[fel", "iz] ¡Ho", "la!"])
    bus, service, resources, record = harness()
    bus.user_message.emit("hola")
    pump(lambda: record["done"] == 1)
    assert "".join(record["tokens"]) == "¡Hola!"
    assert record["states"][:2] == [PetState.THINKING, PetState.HAPPY]
    assert resources.busy_calls == [True, False]
    assert not service.is_busy


def test_truncated_answer_warns_but_notice_stays_out_of_history(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"], finish="length")
    bus, _, _, record = harness()
    bus.user_message.emit("uno")
    pump(lambda: record["done"] == 1)
    assert record["tokens"] == ["Hola"]
    assert record["notices"] == [conversation.TRUNCATED_NOTICE]
    bus.user_message.emit("dos")
    pump(lambda: record["done"] == 2)
    assert seen[1][2]["content"] == "Hola"


def test_complete_answer_has_no_notice(harness, monkeypatch):
    install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("uno")
    pump(lambda: record["done"] == 1)
    assert record["tokens"] == ["Hola"]


def test_history_is_trimmed_in_one_step_and_keeps_a_stable_start(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] ok"])
    bus, service, _, record = harness()
    first_kept = []
    for turn in range(conversation.MAX_HISTORY_MESSAGES // 2 + 3):
        bus.user_message.emit(f"mensaje {turn}")
        pump(lambda current=turn: record["done"] == current + 1)
        first_kept.append(seen[-1][1]["content"])
    assert first_kept[:15] == ["mensaje 0"] * 15
    assert len(set(first_kept)) == 2
    assert seen[-1][1]["role"] == "user"


def test_relevant_knowledge_reaches_the_model(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("¿Conoces a Miku?")
    pump(lambda: record["done"] == 1)
    assert "Dato de Miku." in seen[0][-1]["content"]
    assert seen[0][-1]["content"].endswith("¿Conoces a Miku?")
    assert "Dato de Miku." not in seen[0][0]["content"]


def test_feelings_only_reach_the_model_when_asked(qapp, settings, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus = EventBus()
    done = []
    bus.assistant_done.connect(lambda: done.append(True))
    knowledge = KnowledgeBase([Entry("miku", ("miku",), "Dato.", "Es tu rival.")])
    service = conversation.ConversationService(bus, FakeResources(), settings, knowledge)
    bus.user_message.emit("¿Quién es Miku?")
    pump(lambda: len(done) == 1)
    bus.user_message.emit("¿Qué opinas de Miku?")
    pump(lambda: len(done) == 2)
    assert "Es tu rival." not in seen[0][-1]["content"]
    assert "Es tu rival." in seen[1][-1]["content"]
    assert service is not None


def test_knowledge_stays_out_of_history(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("Háblame de Miku")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("¿Qué tiempo hace?")
    pump(lambda: record["done"] == 2)
    assert seen[1][1]["content"] == "Háblame de Miku"


def test_follow_up_keeps_previous_topic(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("Háblame de Miku")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("¿Y qué sientes?")
    pump(lambda: record["done"] == 2)
    assert "Dato de Miku." in seen[1][-1]["content"]


def test_follow_up_wins_over_keyword_of_other_entry(qapp, settings, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus = EventBus()
    done = []
    bus.assistant_done.connect(lambda: done.append(True))
    knowledge = KnowledgeBase(
        [
            Entry("miku", ("miku",), "Dato de Miku.", ""),
            Entry("programa", ("programa",), "Este programa salió ayer.", ""),
        ]
    )
    service = conversation.ConversationService(bus, FakeResources(), settings, knowledge)
    bus.user_message.emit("Háblame de Miku")
    pump(lambda: len(done) == 1)
    bus.user_message.emit("¿Y cuándo salió?")
    pump(lambda: len(done) == 2)
    assert "Dato de Miku." in seen[1][-1]["content"]
    assert "salió ayer" not in seen[1][-1]["content"]
    assert service is not None


def test_new_topic_does_not_inherit_previous_entry(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("Háblame de Miku")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Cuéntame un chiste")
    pump(lambda: record["done"] == 2)
    assert "Dato de Miku." not in seen[1][-1]["content"]


def test_unrelated_message_adds_no_knowledge(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("¿Qué tiempo hace?")
    pump(lambda: record["done"] == 1)
    assert "Consulta" not in seen[0][-1]["content"]


def test_history_is_sent_on_next_turn(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    bus, _, _, record = harness()
    bus.user_message.emit("uno")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("dos")
    pump(lambda: record["done"] == 2)
    assert [m["content"] for m in seen[1][1:]] == ["uno", "Hola", "dos"]
    assert seen[1][0]["role"] == "system"


def test_message_while_busy_is_ignored(harness, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] a", "b", "c"], pause=0.02)
    bus, _, _, record = harness()
    bus.user_message.emit("uno")
    bus.user_message.emit("dos")
    pump(lambda: record["done"] == 1)
    assert len(seen) == 1


def test_empty_message_is_ignored(harness, monkeypatch):
    seen = install_client(monkeypatch)
    bus, service, _, _ = harness()
    bus.user_message.emit("   ")
    assert not service.is_busy
    assert seen == []


def test_stop_ends_turn_and_keeps_partial_text(harness, monkeypatch):
    install_client(monkeypatch, ["[neutral] a", "b", "c", "d", "e"], pause=0.03)
    bus, _, _, record = harness()
    bus.user_message.emit("hola")
    pump(lambda: record["tokens"])
    bus.generation_stop_requested.emit()
    pump(lambda: record["done"] == 1)
    assert len(record["tokens"]) < 5


def test_load_failure_shows_friendly_error(harness, monkeypatch):
    install_client(monkeypatch)
    bus, service, _, record = harness(FakeResources(LLMStartError("detalle interno")))
    bus.user_message.emit("hola")
    pump(lambda: record["errors"])
    assert "detalle interno" not in record["errors"][0]
    assert record["states"][-1] is PetState.CONFUSED
    assert not service.is_busy


def test_failed_turn_is_removed_from_history(harness, monkeypatch):
    install_client(monkeypatch, error=LLMRequestError("corte"))
    bus, service, _, record = harness()
    bus.user_message.emit("hola")
    pump(lambda: record["errors"])
    seen = install_client(monkeypatch, ["[neutral] ok"])
    bus.user_message.emit("otra vez")
    pump(lambda: record["done"] == 1)
    assert [m["content"] for m in seen[0][1:]] == ["otra vez"]


class FakeLookup:
    def __init__(self, result):
        self.result = result
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.result


WEB_RESULT = WebResult(("VocaDB, artista: Kikuo.",), ("https://vocadb.net/Ar/470",))


@pytest.fixture
def web_harness(qapp, settings, monkeypatch):
    services = []

    def make(result=WEB_RESULT, enabled=True):
        seen = install_client(monkeypatch, ["[neutral] Hola"])
        settings.set("web.enabled", enabled)
        bus = EventBus()
        record = {"done": 0, "notices": [], "status": []}
        bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
        bus.assistant_notice.connect(record["notices"].append)
        bus.assistant_status.connect(record["status"].append)
        knowledge = KnowledgeBase([Entry("miku", ("miku",), "Dato de Miku.", "")])
        lookup = FakeLookup(result)
        service = conversation.ConversationService(
            bus, FakeResources(), settings, knowledge, lookup
        )
        services.append(service)
        return bus, service, lookup, seen, record

    return make


def test_web_is_off_by_default(harness, monkeypatch, settings):
    assert settings.get("web.enabled") is False


def test_disabled_web_sends_nothing(web_harness):
    bus, _, lookup, seen, record = web_harness(enabled=False)
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    assert lookup.queries == []
    assert "Kikuo." not in seen[0][-1]["content"].split("Mensaje")[0]


def test_disabled_web_is_mentioned_when_it_would_help(web_harness):
    bus, _, _, _, record = web_harness(enabled=False)
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    assert record["notices"] == [conversation.WEB_OFF_NOTICE]


@pytest.mark.parametrize("text", ["Hola, ¿qué tal?", "¿Quién es Miku?"])
def test_disabled_web_is_not_mentioned_when_useless(web_harness, text):
    bus, _, _, _, record = web_harness(enabled=False)
    bus.user_message.emit(text)
    pump(lambda: record["done"] == 1)
    assert record["notices"] == []


def test_web_facts_reach_the_model_and_source_is_cited(web_harness):
    bus, _, lookup, seen, record = web_harness()
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    assert [query.topic for query in lookup.queries] == ["Kikuo"]
    assert "VocaDB, artista: Kikuo." in seen[0][-1]["content"]
    assert seen[0][-1]["content"].endswith("¿Quién es Kikuo?")
    assert "https://vocadb.net/Ar/470" in record["notices"][0]
    assert "Buscando en VocaDB…" in record["status"]


def test_web_facts_stay_out_of_history(web_harness):
    bus, _, _, seen, record = web_harness()
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Otra cosa")
    pump(lambda: record["done"] == 2)
    assert seen[1][1]["content"] == "¿Quién es Kikuo?"


def test_local_entry_avoids_the_network(web_harness):
    bus, _, lookup, seen, record = web_harness()
    bus.user_message.emit("¿Quién es Miku?")
    pump(lambda: record["done"] == 1)
    assert lookup.queries == []
    assert "Dato de Miku." in seen[0][-1]["content"]


def test_song_list_searches_even_with_local_entry(web_harness):
    bus, _, lookup, seen, record = web_harness()
    bus.user_message.emit("Dime canciones de Miku")
    pump(lambda: record["done"] == 1)
    assert lookup.queries[0].wants_songs
    assert "Dato de Miku." in seen[0][-1]["content"]
    assert "VocaDB, artista" in seen[0][-1]["content"]


def test_unrelated_message_never_leaves_the_app(web_harness):
    bus, _, lookup, _, record = web_harness()
    bus.user_message.emit("Hoy tuve un día horrible en el trabajo")
    pump(lambda: record["done"] == 1)
    assert lookup.queries == []


def test_follow_up_reuses_web_data_without_new_request(web_harness):
    bus, _, lookup, seen, record = web_harness()
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("¿Y cuándo empezó su carrera?")
    pump(lambda: record["done"] == 2)
    assert len(lookup.queries) == 1
    assert "VocaDB, artista: Kikuo." in seen[1][-1]["content"]
    assert len(record["notices"]) == 2


def test_follow_up_does_not_activate_entries_by_a_loose_word(qapp, settings, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    settings.set("web.enabled", True)
    bus = EventBus()
    done = []
    bus.assistant_done.connect(lambda: done.append(True))
    knowledge = KnowledgeBase([Entry("kaito", ("kaito",), "Empezó su carrera en 2006.", "")])
    service = conversation.ConversationService(
        bus, FakeResources(), settings, knowledge, FakeLookup(WEB_RESULT)
    )
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: len(done) == 1)
    bus.user_message.emit("¿Y cuándo empezó su carrera?")
    pump(lambda: len(done) == 2)
    assert "2006" not in seen[1][-1]["content"]
    assert "VocaDB, artista: Kikuo." in seen[1][-1]["content"]
    assert service is not None


def test_web_data_only_lasts_one_step(web_harness):
    bus, _, _, seen, record = web_harness()
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Cuéntame un chiste")
    pump(lambda: record["done"] == 2)
    bus.user_message.emit("¿Y cuándo salió?")
    pump(lambda: record["done"] == 3)
    assert "VocaDB" not in seen[2][-1]["content"]


def test_turning_web_off_forgets_previous_data(web_harness):
    bus, service, _, seen, record = web_harness()
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    bus.web_enabled_requested.emit(False)
    bus.user_message.emit("¿Y cuándo salió?")
    pump(lambda: record["done"] == 2)
    assert not service.web_enabled
    assert "VocaDB" not in seen[1][-1]["content"]


def test_failed_search_warns_and_still_answers(web_harness):
    bus, _, _, _, record = web_harness(WebResult(failed=True))
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    assert record["notices"] == [conversation.WEB_FAILED_NOTICE]


def test_stop_during_search_skips_the_model(web_harness):
    bus, _, lookup, seen, record = web_harness()

    def stopped_search(query):
        bus.generation_stop_requested.emit()
        time.sleep(0.05)
        return WEB_RESULT

    lookup.search = stopped_search
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: record["done"] == 1)
    assert seen == []


def test_empty_answer_is_reported_and_drops_the_source(web_harness, monkeypatch):
    bus, _, _, _, record = web_harness()
    install_client(monkeypatch, ["[neutral] "])
    errors = []
    bus.assistant_error.connect(errors.append)
    bus.user_message.emit("¿Quién es Kikuo?")
    pump(lambda: errors)
    assert errors == [conversation.EMPTY_ANSWER_MESSAGE]
    assert record["notices"] == []


def test_correction_note_reaches_the_chat(web_harness):
    result = WebResult(("x",), ("https://vocadb.net/Ar/470",), note='Entendí "Kikuho" y busqué "Kikuo".')
    bus, _, _, _, record = web_harness(result)
    bus.user_message.emit("¿Quién es Kikuho?")
    pump(lambda: record["done"] == 1)
    assert 'Entendí "Kikuho"' in record["notices"][0]


def test_misspelled_local_name_uses_the_entry_without_network(qapp, settings, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    settings.set("web.enabled", True)
    bus = EventBus()
    done = []
    bus.assistant_done.connect(lambda: done.append(True))
    knowledge = KnowledgeBase([Entry("senbonzakura", ("Senbonzakura",), "Es de KurousaP.", "")])
    lookup = FakeLookup(WEB_RESULT)
    service = conversation.ConversationService(bus, FakeResources(), settings, knowledge, lookup)
    bus.user_message.emit("senbozakura")
    pump(lambda: len(done) == 1)
    bus.user_message.emit("¿Quién hizo Sembo Sakura?")
    pump(lambda: len(done) == 2)
    assert "KurousaP" in seen[0][-1]["content"]
    assert "KurousaP" in seen[1][-1]["content"]
    assert lookup.queries == []
    assert service is not None


def test_search_again_looks_for_the_previous_topic(web_harness):
    bus, _, lookup, _, record = web_harness(WebResult())
    bus.user_message.emit("¿Quién hizo Fulanito?")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Puedes buscarlo en Boga de V, por favor.")
    pump(lambda: record["done"] == 2)
    assert [query.topic for query in lookup.queries] == ["Fulanito", "Fulanito"]
    assert lookup.queries[1].explicit


def test_genre_word_in_the_sentence_does_not_block_the_search(qapp, settings, monkeypatch):
    seen = install_client(monkeypatch, ["[neutral] Hola"])
    settings.set("web.enabled", True)
    bus = EventBus()
    done = []
    bus.assistant_done.connect(lambda: done.append(True))
    knowledge = KnowledgeBase([Entry("vocaloid", ("Vocaloid",), "Lo hizo Yamaha.", "")])
    lookup = FakeLookup(WEB_RESULT)
    service = conversation.ConversationService(bus, FakeResources(), settings, knowledge, lookup)
    bus.user_message.emit("Estoy preguntando por KikuO el productor de canciones de Vocaloid.")
    pump(lambda: len(done) == 1)
    assert [query.topic for query in lookup.queries] == ["KikuO"]
    assert "Yamaha" not in seen[0][-1]["content"]
    assert "VocaDB, artista: Kikuo." in seen[0][-1]["content"]
    assert service is not None


def test_search_again_tells_the_model_it_is_already_done(web_harness):
    bus, _, _, seen, record = web_harness()
    bus.user_message.emit("¿Quién hizo Fulanito?")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Búscalo, por favor")
    pump(lambda: record["done"] == 2)
    assert "Ya has buscado" in seen[1][-1]["content"]
    assert "Ya has buscado" not in seen[0][-1]["content"]


def test_no_results_add_no_block_or_source(web_harness):
    bus, _, _, seen, record = web_harness(WebResult())
    bus.user_message.emit("¿Quién es Fulanito?")
    pump(lambda: record["done"] == 1)
    assert "Consulta" not in seen[0][-1]["content"]
    assert record["notices"] == []


GPU = AiProfile("gpu", "g", 99)
CPU = AiProfile("cpu", "c", 0)


@pytest.mark.parametrize(
    ("device", "free", "expected"),
    [
        ("auto", 3500, [GPU, CPU]),
        ("auto", 1000, [CPU]),
        ("auto", None, [CPU]),
        ("gpu", 1000, [GPU, CPU]),
        ("cpu", 3500, [CPU]),
    ],
)
def test_choose_profiles(device, free, expected):
    assert choose_profiles(device, GPU, CPU, free, 3100) == expected
