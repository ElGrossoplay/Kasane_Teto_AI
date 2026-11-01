import sqlite3

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from kasane_teto.core.events import EventBus
from kasane_teto.interface.chat_window import ChatWindow
from kasane_teto.interface.memory_window import MemoryWindow
from kasane_teto.memory import store as store_module
from kasane_teto.memory.proposals import asks_memories, detect_proposal, read_answer
from kasane_teto.memory.store import MemoryStore, MemoryStoreError


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.sqlite3")


def test_memories_survive_reopening(tmp_path):
    path = tmp_path / "memory.sqlite3"
    MemoryStore(path).add("hecho", "mi perro se llama Toby")
    assert [m.content for m in MemoryStore(path).all()] == ["mi perro se llama Toby"]


@pytest.mark.parametrize(
    "question",
    ["¿Cómo se llama mi perro?", "¿Recuerdas el nombre de mi Perro?", "Hablemos de perros"],
)
def test_search_finds_related_memory(store, question):
    store.add("hecho", "mi perro se llama Toby")
    store.add("preferencia", "me gusta el café")
    assert any("Toby" in m.content for m in store.search(question, 3))


def test_search_stem_matches_other_forms(store):
    store.add("hecho", "mi perro se llama Toby")
    assert [m.content for m in store.search("¿Cómo llamo a mi perro?", 3)] == [
        "mi perro se llama Toby"
    ]


@pytest.mark.parametrize(
    "question",
    ["¿Cómo te llamas?", "¿Qué te gusta?", "¿Cómo se llama la voz de Miku?", "¿Cuál es tu favorita?"],
)
def test_questions_about_others_do_not_pull_personal_memories(store, question):
    store.add("hecho", "Me llamo Diego")
    store.add("preferencia", "Me gusta el café")
    store.add("preferencia", "Mi canción favorita es Mesmerizer")
    assert store.search(question, 3) == []


def test_name_of_a_saved_person_is_still_found_without_first_person(store):
    store.add("hecho", "mi perro se llama Toby")
    assert store.search("¿Quién es Toby?", 3)


def test_search_respects_accents_and_limit(store):
    for index in range(5):
        store.add("hecho", f"música favorita número {index}")
    assert len(store.search("musica", 3)) == 3


def test_search_with_only_common_words_finds_nothing(store):
    store.add("hecho", "me gusta el café")
    assert store.search("¿qué tal?", 3) == []


def test_search_survives_fts_syntax_in_the_question(store):
    store.add("hecho", "me gusta el café")
    assert store.search('NEAR( "café" AND -- *', 3)


def test_edit_updates_search(store):
    memory_id = store.add("hecho", "me gusta el café")
    store.update(memory_id, "me gusta el mate")
    assert store.search("café", 3) == []
    assert store.search("mate", 3)[0].id == memory_id


def test_delete_removes_from_search(store):
    memory_id = store.add("hecho", "me gusta el café")
    store.delete(memory_id)
    assert store.search("café", 3) == []
    assert store.all() == []


def test_clear_removes_everything(store):
    store.add("hecho", "uno cosas")
    store.add("hecho", "dos cosas")
    store.clear()
    assert store.all() == []
    assert store.search("cosas", 3) == []


def test_deleted_text_does_not_stay_in_the_file(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)
    store.add("hecho", "secretoinconfundible")
    store.clear()
    assert b"secretoinconfundible" not in path.read_bytes()


def test_single_delete_and_edit_also_leave_no_trace(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)
    store.add("hecho", "se queda esto")
    deleted = store.add("hecho", "borradoinconfundible")
    edited = store.add("hecho", "editadoinconfundible")
    store.delete(deleted)
    store.update(edited, "texto nuevo")
    data = path.read_bytes()
    assert b"borradoinconfundible" not in data
    assert b"editadoinconfundible" not in data
    assert store.search("nuevo", 3)
    assert store.search("queda", 3)


def test_deleted_conversation_leaves_no_trace(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)
    conversation = store.start_conversation()
    store.add_message(conversation, "user", "charlainconfundible")
    store.clear_history()
    assert b"charlainconfundible" not in path.read_bytes()


def test_content_is_cleaned_and_limited(store):
    store.add("hecho", "  mucho   espacio  " + "x" * 500)
    content = store.all()[0].content
    assert content.startswith("mucho espacio x")
    assert len(content) == store_module.MAX_CONTENT_CHARS


def test_contains_ignores_case_and_accents(store):
    store.add("hecho", "Me gusta el café")
    assert store.contains("me gusta el cafe")
    assert not store.contains("me gusta el té")


def test_panel_filter_finds_part_of_a_word(store):
    store.add("hecho", "mi perro se llama Toby")
    assert len(store.all("tob")) == 1
    assert store.all("gato") == []


def test_history_keeps_order_and_counts(store):
    conversation = store.start_conversation()
    store.add_message(conversation, "user", "hola")
    store.add_message(conversation, "assistant", "qué tal")
    assert [m.content for m in store.messages(conversation)] == ["hola", "qué tal"]
    assert store.conversations()[0].messages == 2


def test_deleting_a_conversation_deletes_its_messages(store):
    conversation = store.start_conversation()
    store.add_message(conversation, "user", "hola")
    store.delete_conversation(conversation)
    assert store.conversations() == []
    assert store.messages(conversation) == []


def test_history_and_memories_are_deleted_separately(store):
    store.add("hecho", "recuerdo")
    store.add_message(store.start_conversation(), "user", "hola")
    store.clear_history()
    assert len(store.all()) == 1
    assert store.conversations() == []


def test_unreadable_file_raises_controlled_error(tmp_path):
    path = tmp_path / "memory.sqlite3"
    path.write_bytes(b"esto no es una base de datos" * 100)
    with pytest.raises(MemoryStoreError):
        MemoryStore(path)


def test_error_during_use_is_controlled(store, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disco lleno")

    monkeypatch.setattr(store_module.sqlite3, "connect", broken)
    with pytest.raises(MemoryStoreError):
        store.add("hecho", "algo")


@pytest.mark.parametrize(
    ("text", "kind", "content"),
    [
        ("Recuerda que mi perro se llama Toby.", "hecho", "mi perro se llama Toby"),
        ("Oye, recuérdame que el martes tengo dentista", "hecho", "el martes tengo dentista"),
        ("No olvides que soy alérgico al polen", "hecho", "soy alérgico al polen"),
        ("Acuérdate de que juego al LoL", "hecho", "juego al LoL"),
        ("Guarda esto: uso Windows 11", "hecho", "uso Windows 11"),
    ],
)
def test_explicit_request_is_proposed(text, kind, content):
    proposal = detect_proposal(text)
    assert proposal is not None
    assert (proposal.kind, proposal.content, proposal.explicit) == (kind, content, True)


@pytest.mark.parametrize(
    ("text", "kind", "content"),
    [
        ("Me llamo Diego.", "hecho", "Me llamo Diego"),
        ("Me gustan los gatos", "preferencia", "Me gustan los gatos"),
        ("No me gusta el pepino.", "preferencia", "No me gusta el pepino"),
        ("Mi canción favorita es Mesmerizer", "preferencia", "Mi canción favorita es Mesmerizer"),
        ("Tengo 25 años", "hecho", "Tengo 25 años"),
        ("Hola. Mi gato se llama Pelusa.", "hecho", "Mi gato se llama Pelusa"),
    ],
)
def test_clear_personal_sentences_are_proposed(text, kind, content):
    proposal = detect_proposal(text)
    assert proposal is not None
    assert (proposal.kind, proposal.content, proposal.explicit) == (kind, content, False)


@pytest.mark.parametrize(
    "text",
    [
        "Hola, ¿cómo estás?",
        "¿Me gusta el pepino?",
        "¿Cómo me llamo?",
        "Cuéntame un chiste",
        "Hoy tuve un día horrible en el trabajo",
        "¿Quién es Kikuo?",
        "Dime canciones de Miku",
        "Trabajo",
    ],
)
def test_ordinary_messages_are_not_proposed(text):
    assert detect_proposal(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Recuerda que mi contraseña es gato123",
        "Recuerda que el PIN es 4321",
        "Recuerda que mi tarjeta termina en 1234",
        "Recuerda que mi teléfono es 600123456",
        "Recuerda que mi correo es ana@correo.com",
        "Mi clave favorita es hola",
    ],
)
def test_secrets_are_never_proposed(text):
    assert detect_proposal(text) is None


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("sí", True),
        ("Sí, guárdalo.", True),
        ("si por favor", True),
        ("no", False),
        ("No, gracias", False),
        ("Hoy hace sol", None),
        ("No sé qué decirte", None),
        ("Sí que me gusta", None),
    ],
)
def test_read_answer_needs_a_clear_reply(text, answer):
    assert read_answer(text) is answer


@pytest.mark.parametrize("text", ["¿Qué recuerdas de mí?", "¿Qué sabes sobre mí?", "Qué recuerdas"])
def test_asks_memories(text):
    assert asks_memories(text)


def test_question_about_someone_else_is_not_about_memories():
    assert not asks_memories("¿Qué sabes de Kikuo?")


@pytest.fixture
def panel(qapp, store):
    window = MemoryWindow(store)
    yield window
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def texts(widget):
    return [widget.item(i).text() for i in range(widget.count())]


def answer_question(monkeypatch, button):
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: button)


def test_panel_lists_and_filters(store, qapp):
    store.add("hecho", "mi perro se llama Toby")
    store.add("hecho", "me gusta el café")
    window = MemoryWindow(store)
    assert len(texts(window._memories)) == 2
    window._search.setText("toby")
    assert texts(window._memories) == ["mi perro se llama Toby"]
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_panel_add_is_saved(panel, store, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("me gusta el mate", True))
    panel._add_memory()
    assert texts(panel._memories) == ["me gusta el mate"]
    assert len(store.all()) == 1


def test_panel_edit_changes_the_memory(store, qapp, monkeypatch):
    store.add("hecho", "me gusta el café")
    window = MemoryWindow(store)
    window._memories.setCurrentRow(0)
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("me gusta el té", True))
    window._edit_memory()
    assert store.all()[0].content == "me gusta el té"
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize(
    ("button", "remaining"),
    [(QMessageBox.StandardButton.No, 1), (QMessageBox.StandardButton.Yes, 0)],
)
def test_panel_delete_asks_first(store, qapp, monkeypatch, button, remaining):
    store.add("hecho", "me gusta el café")
    window = MemoryWindow(store)
    window._memories.setCurrentRow(0)
    answer_question(monkeypatch, button)
    window._delete_memory()
    assert len(store.all()) == remaining
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_panel_shows_and_deletes_history(store, qapp, monkeypatch):
    conversation = store.start_conversation()
    store.add_message(conversation, "user", "hola")
    store.add_message(conversation, "assistant", "qué tal")
    window = MemoryWindow(store)
    window._conversations.setCurrentRow(0)
    assert "Tú: hola" in window._messages.toPlainText()
    assert "Teto: qué tal" in window._messages.toPlainText()
    answer_question(monkeypatch, QMessageBox.StandardButton.Yes)
    window._delete_conversation()
    assert store.conversations() == []
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_panel_reports_database_errors(store, qapp, monkeypatch):
    window = MemoryWindow(store)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    def broken(*args):
        raise MemoryStoreError("roto")

    monkeypatch.setattr(store, "all", broken)
    window._reload_memories()
    assert warnings
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_chat_bar_shows_proposal_and_answers(qapp):
    bus = EventBus()
    window = ChatWindow(bus)
    answers = []
    bus.memory_answered.connect(answers.append)
    bus.memory_proposed.emit("me gusta el café")
    assert not window._proposal_bar.isHidden()
    assert "me gusta el café" in window._proposal.text()
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window._remember.click()
    window._forget.click()
    assert answers == [True, False]
    bus.memory_proposed.emit("")
    assert window._proposal_bar.isHidden()
    window.close()
