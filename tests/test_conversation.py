import time

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer

import kasane_teto.core.conversation as conversation
from kasane_teto.ai.llm_client import LLMRequestError
from kasane_teto.ai.llm_process import LLMStartError
from kasane_teto.character.states import PetState
from kasane_teto.core.events import EventBus
from kasane_teto.core.resource_manager import AiProfile, choose_profiles


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


def install_client(monkeypatch, chunks=(), error=None, pause=0.0):
    seen = []

    class FakeClient:
        def __init__(self, base_url, api_key):
            pass

        def stream_chat(self, messages, params, cancel):
            seen.append(messages)
            for chunk in chunks:
                if cancel.is_set():
                    return
                time.sleep(pause)
                yield chunk
            if error:
                raise error

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
        record = {"tokens": [], "states": [], "done": 0, "errors": []}
        bus.assistant_token.connect(record["tokens"].append)
        bus.pet_state_requested.connect(record["states"].append)
        bus.assistant_error.connect(record["errors"].append)
        bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
        resources = resources or FakeResources()
        service = conversation.ConversationService(bus, resources, settings)
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
