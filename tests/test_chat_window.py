import pytest

from kasane_teto.core.events import EventBus
from kasane_teto.interface.chat_window import ChatWindow


@pytest.fixture
def chat(qapp):
    bus = EventBus()
    window = ChatWindow(bus)
    sent = []
    bus.user_message.connect(sent.append)
    yield bus, window, sent
    window.close()


def type_and_send(window, text):
    window._input.setText(text)
    window._input.returnPressed.emit()


def test_send_shows_message_and_locks_input(chat):
    _, window, sent = chat
    type_and_send(window, "  hola  ")
    assert sent == ["hola"]
    assert window._input.text() == ""
    assert "Tú: hola" in window._log.toPlainText()
    assert window._stop.isEnabled()
    assert not window._send.isEnabled()


def test_second_message_is_blocked_while_generating(chat):
    _, window, sent = chat
    type_and_send(window, "uno")
    type_and_send(window, "dos")
    assert sent == ["uno"]


def test_empty_message_is_not_sent(chat):
    _, window, sent = chat
    type_and_send(window, "   ")
    assert sent == []


def test_answer_is_labelled_once_and_unlocks(chat):
    bus, window, _ = chat
    type_and_send(window, "hola")
    bus.assistant_token.emit("Ho")
    bus.assistant_token.emit("la")
    bus.assistant_done.emit()
    assert "Teto: Hola\n" in window._log.toPlainText()
    assert window._log.toPlainText().count("Teto:") == 1
    assert window._send.isEnabled()
    assert not window._stop.isEnabled()


def test_error_is_shown_and_unlocks(chat):
    bus, window, _ = chat
    type_and_send(window, "hola")
    bus.assistant_error.emit("No pude cargar la IA.")
    assert "No pude cargar la IA." in window._log.toPlainText()
    assert window._send.isEnabled()


def test_stop_button_requests_stop(chat):
    bus, window, _ = chat
    stops = []
    bus.generation_stop_requested.connect(lambda: stops.append(True))
    type_and_send(window, "hola")
    window._stop.click()
    assert stops == [True]
