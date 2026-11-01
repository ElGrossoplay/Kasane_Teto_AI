import ast
import time
import zipfile
from pathlib import Path

import pytest
from pptx import Presentation
from PySide6.QtCore import QCoreApplication, QElapsedTimer

import kasane_teto.core.conversation as conversation
from kasane_teto.core.comments import CommentService, load_game_lines
from kasane_teto.core.events import EventBus
from kasane_teto.interface.chat_window import ChatWindow
from kasane_teto.memory.knowledge import Entry, KnowledgeBase
from kasane_teto.personality.prompt_builder import system_prompt_for
from kasane_teto.tools import documents
from kasane_teto.tools.commands import (
    LOOK_AT_SCREEN,
    WRITE_DOCUMENT,
    Command,
    asks_open_things,
    parse_command,
)
from kasane_teto.tools.registry import ToolRegistry
from kasane_teto.tools.screen_capture import CaptureError
from kasane_teto.tools.windows_control import Foreground, Window

SOURCE = Path(conversation.__file__).parents[1]


@pytest.mark.parametrize(
    "text",
    ["Mira mi pantalla", "¿Qué hay en mi pantalla?", "Analiza la pantalla", "¿Qué ves?",
     "Teto, mírame la pantalla por favor", "Describe esta pantalla"],
)
def test_look_orders_are_recognised(text):
    assert parse_command(text) == Command(LOOK_AT_SCREEN)


@pytest.mark.parametrize(
    ("text", "what", "kind"),
    [
        ("Escribe un poema en el bloc de notas", "un poema", "txt"),
        ("Escribe una carta a mi jefe en Word", "una carta a mi jefe", "docx"),
        ("Hazme un resumen de Vocaloid en un documento de Word.", "un resumen de Vocaloid", "docx"),
        ("Crea una presentación sobre Kasane Teto", "Kasane Teto", "pptx"),
        ("Haz un PowerPoint sobre los gatos", "los gatos", "pptx"),
        ("Crea un documento sobre el cambio climático", "el cambio climático", "docx"),
    ],
)
def test_write_orders_are_recognised(text, what, kind):
    assert parse_command(text) == Command(WRITE_DOCUMENT, what, kind)


@pytest.mark.parametrize(
    "text", ["¿Qué tengo abierto?", "¿Qué ventanas tengo?", "¿Qué estoy viendo?", "¿Qué tengo delante?"]
)
def test_open_things_questions(text):
    assert asks_open_things(text)


@pytest.mark.parametrize(
    "text",
    ["Escribe algo bonito", "¿Qué opinas de Word?", "Háblame de mi pantalla nueva", "Me gusta Word"],
)
def test_conversation_is_not_a_document_or_screen_order(text):
    command = parse_command(text)
    assert command is None or command.kind not in (LOOK_AT_SCREEN, WRITE_DOCUMENT)


def test_text_file_is_new_and_keeps_accents(tmp_path):
    path = documents.create_document("txt", "Canción ñandú", tmp_path / "Teto")
    assert path.parent == tmp_path / "Teto"
    assert path.suffix == ".txt"
    assert path.read_text(encoding="utf-8") == "Canción ñandú"


def test_files_never_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(documents.time, "strftime", lambda _format: "fija")
    first = documents.create_document("txt", "uno", tmp_path)
    second = documents.create_document("txt", "dos", tmp_path)
    assert first != second
    assert first.read_text(encoding="utf-8") == "uno"


def test_word_file_is_valid_and_escapes_text(tmp_path):
    path = documents.create_document("docx", "Título <raro> & más\nSegunda línea", tmp_path)
    with zipfile.ZipFile(path) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
        assert archive.testzip() is None
    assert "Título &lt;raro&gt; &amp; más" in body
    assert "Segunda línea" in body


def test_preamble_is_removed_from_documents():
    assert documents.strip_preamble("Aquí tienes el poema:\n\nGatos\nSiempre") == "Gatos\nSiempre"
    assert documents.strip_preamble("Querido amigo:\nGracias") == "Gracias"
    assert documents.strip_preamble("Texto sin más") == "Texto sin más"
    assert documents.strip_preamble("Solo esto:") == "Solo esto:"


def test_second_order_is_not_part_of_the_app_name():
    assert parse_command("Abre Discord y dime un chiste") == Command("app", "Discord")
    assert parse_command("Abre Steam, luego cierra Word") == Command("app", "Steam")


def test_document_model_gets_the_topic_without_the_persona(desktop):
    bus, _, _, seen, record, *_ = desktop
    bus.user_message.emit("Crea una presentación sobre Kasane Teto")
    pump(lambda: record["done"] == 1)
    messages = seen[0][0]
    assert "redactora" in messages[0]["content"]
    assert messages[-1]["content"].endswith("Kasane Teto")
    assert "Crea una" not in messages[-1]["content"]


def test_document_uses_verified_entries(qapp, settings, tmp_path, monkeypatch):
    seen = []

    class FakeClient:
        finish_reason = "stop"

        def __init__(self, base_url, api_key):
            pass

        def stream_chat(self, messages, params, cancel):
            seen.append(messages)
            yield "[neutral] Texto"

    monkeypatch.setattr(conversation, "LLMClient", FakeClient)
    settings.set("tools.enabled", True)
    tools = ToolRegistry(settings, tmp_path / "a.log", FakeRunner(), {"documentos": tmp_path})
    bus = EventBus()
    done = []
    bus.assistant_done.connect(lambda: done.append(True))
    knowledge = KnowledgeBase([Entry("miku", ("Miku",), "Dato verificado.", "Sentimiento.")])
    service = conversation.ConversationService(
        bus, FakeResources(), settings, knowledge, tools=tools
    )
    bus.user_message.emit("Crea una presentación sobre Miku")
    pump(lambda: done)
    assert "Dato verificado." in seen[0][-1]["content"]
    assert "Sentimiento." not in seen[0][-1]["content"]
    assert service is not None


def test_slides_are_split_by_blank_lines():
    slides = documents.split_slides("Inicio\n- uno\n- dos\n\nFinal\ntres")
    assert slides == [("Inicio", ["uno", "dos"]), ("Final", ["tres"])]


def test_presentation_opens_with_its_slides(tmp_path):
    path = documents.create_document("pptx", "Inicio\n- uno\n\nFinal\n- dos", tmp_path)
    slides = list(Presentation(str(path)).slides)
    assert [slide.shapes.title.text for slide in slides] == ["Inicio", "Final"]


class FakeRunner:
    def __init__(self):
        self.opened = []
        self.windows = []
        self.current = Foreground("", False)
        self.game = False
        self.idle = 0.0

    def open_path(self, path):
        self.opened.append(path)

    def list_windows(self):
        return self.windows

    def foreground(self):
        return self.current

    def game_on_screen(self):
        return self.game

    def seconds_since_input(self):
        return self.idle


class FakeResources:
    def __init__(self):
        self.vision_calls = 0

    def ensure_loaded(self, vision=False):
        self.vision_calls += vision
        return type("Process", (), {"base_url": "http://fake", "api_key": "k"})()

    def set_busy(self, busy):
        pass


def pump(condition, timeout_ms=3000):
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        QCoreApplication.processEvents()
        time.sleep(0.002)
    assert condition()


@pytest.fixture
def desktop(qapp, settings, tmp_path, monkeypatch):
    seen = []
    captures = []

    class FakeClient:
        finish_reason = "stop"

        def __init__(self, base_url, api_key):
            pass

        def stream_chat(self, messages, params, cancel):
            seen.append((messages, params))
            yield "[neutral] Texto de Teto"

    monkeypatch.setattr(conversation, "LLMClient", FakeClient)
    settings.set("tools.enabled", True)
    runner = FakeRunner()
    folders = {"documentos": tmp_path / "docs"}
    tools = ToolRegistry(settings, tmp_path / "actions.log", runner, folders)
    bus = EventBus()
    record = {"done": 0, "tokens": [], "errors": []}
    bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
    bus.assistant_token.connect(record["tokens"].append)
    bus.assistant_error.connect(record["errors"].append)
    resources = FakeResources()

    def capture():
        captures.append(True)
        return "data:image/jpeg;base64,QUJD"

    service = conversation.ConversationService(
        bus, resources, settings, KnowledgeBase([]), tools=tools, capture=capture
    )
    return bus, service, runner, seen, record, resources, captures, tmp_path


def test_look_sends_the_image_to_the_local_model_only(desktop):
    bus, _, _, seen, record, resources, captures, _ = desktop
    bus.user_message.emit("Mira mi pantalla")
    pump(lambda: record["done"] == 1)
    content = seen[0][0][-1]["content"]
    assert content[0]["image_url"]["url"].endswith("QUJD")
    assert content[1]["text"].endswith("Mira mi pantalla")
    assert resources.vision_calls == 1
    assert captures == [True]


def test_image_stays_out_of_history(desktop):
    bus, _, _, seen, record, *_ = desktop
    bus.user_message.emit("Mira mi pantalla")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Gracias")
    pump(lambda: record["done"] == 2)
    assert "QUJD" not in repr(seen[1][0])


def test_screen_is_never_captured_with_a_game_open(desktop):
    bus, _, runner, seen, record, _, captures, _ = desktop
    runner.game = True
    bus.user_message.emit("Mira mi pantalla")
    assert record["tokens"] == [conversation.SCREEN_GAME_REPLY]
    assert captures == []
    assert seen == []


def test_screen_is_not_captured_with_tools_off(desktop, settings):
    bus, _, _, _, record, _, captures, _ = desktop
    settings.set("tools.enabled", False)
    bus.user_message.emit("Mira mi pantalla")
    pump(lambda: record["done"] == 1)
    assert captures == []


def test_failed_capture_is_explained(qapp, settings, tmp_path):
    settings.set("tools.enabled", True)

    def broken():
        raise CaptureError("sin pantalla")

    tools = ToolRegistry(settings, tmp_path / "a.log", FakeRunner(), {})
    bus = EventBus()
    tokens = []
    bus.assistant_token.connect(tokens.append)
    service = conversation.ConversationService(
        bus, FakeResources(), settings, KnowledgeBase([]), tools=tools, capture=broken
    )
    bus.user_message.emit("Mira mi pantalla")
    assert tokens == [conversation.SCREEN_FAILED_REPLY]
    assert service is not None


def test_nothing_in_the_app_saves_a_capture_to_disk():
    tree = ast.parse((SOURCE / "tools" / "screen_capture.py").read_text(encoding="utf-8"))
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "write_bytes" not in calls


def test_document_is_created_opened_and_not_read_aloud(desktop):
    bus, _, runner, seen, record, _, _, tmp_path = desktop
    bus.user_message.emit("Escribe un poema en el bloc de notas")
    pump(lambda: record["done"] == 1)
    files = list((tmp_path / "docs" / "Teto").iterdir())
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "Texto de Teto"
    assert runner.opened == files
    assert record["tokens"] == [conversation.DOCUMENT_SAVED_REPLY]
    assert seen[0][1].max_tokens == conversation.DOCUMENT_MAX_TOKENS


def test_document_is_not_created_with_tools_off(desktop, settings):
    bus, _, _, _, record, _, _, tmp_path = desktop
    settings.set("tools.enabled", False)
    bus.user_message.emit("Escribe un poema en el bloc de notas")
    pump(lambda: record["done"] == 1)
    assert not (tmp_path / "docs").exists()


def test_open_windows_only_reach_the_local_model_when_asked(desktop):
    bus, _, runner, seen, record, *_ = desktop
    runner.windows = [Window(1, "Vídeo - YouTube - Google Chrome"), Window(2, "Amigos - Discord")]
    runner.current = Foreground("Amigos - Discord", False)
    bus.user_message.emit("¿Qué tengo abierto?")
    pump(lambda: record["done"] == 1)
    bus.user_message.emit("Cuéntame un chiste")
    pump(lambda: record["done"] == 2)
    first = seen[0][0][-1]["content"]
    assert first.index("Discord") < first.index("YouTube")
    assert "YouTube" not in seen[1][0][-1]["content"]


def test_tools_rule_replaces_the_cannot_rule(desktop):
    bus, _, _, seen, record, *_ = desktop
    bus.user_message.emit("Hola")
    pump(lambda: record["done"] == 1)
    assert "las hace la app" in seen[0][0][0]["content"]
    assert "No puedes hacer acciones" not in seen[0][0][0]["content"]


def test_prompt_is_unchanged_without_tools():
    base = "Regla.\n- No puedes hacer acciones en el ordenador, nada.\n- Otra.\n"
    assert system_prompt_for(base, False) == base


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def comments(qapp, settings, tmp_path):
    settings.set("comments.enabled", True)
    settings.set("comments.minutes", 10)
    runner = FakeRunner()
    tools = ToolRegistry(settings, tmp_path / "a.log", runner, {})
    bus = EventBus()
    said = []
    lines = []
    clock = Clock()
    bus.assistant_token.connect(lines.append)

    def comment(title):
        said.append(title)
        return True

    service = CommentService(bus, settings, tools, comment, clock=clock)
    yield bus, service, runner, said, lines, clock
    service.shutdown()


def test_comments_are_off_by_default(settings):
    assert settings.get("comments.enabled") is False


def test_no_comment_before_the_wait(comments):
    _, service, runner, said, _, clock = comments
    runner.current = Foreground("Vídeo - YouTube", False)
    clock.now += 60
    service.check()
    assert said == []


def test_comment_after_the_wait_uses_the_title(comments):
    _, service, runner, said, _, clock = comments
    runner.current = Foreground("Vídeo - YouTube", False)
    clock.now += 601
    service.check()
    assert said == ["Vídeo - YouTube"]


def test_same_window_is_not_commented_twice(comments):
    _, service, runner, said, _, clock = comments
    runner.current = Foreground("Vídeo - YouTube", False)
    clock.now += 601
    service.check()
    clock.now += 601
    service.check()
    assert said == ["Vídeo - YouTube"]


def test_no_comment_when_nobody_is_there(comments):
    _, service, runner, said, _, clock = comments
    runner.current = Foreground("Vídeo - YouTube", False)
    runner.idle = 3600
    clock.now += 601
    service.check()
    assert said == []


def test_game_uses_a_prepared_line_and_never_the_model(comments):
    _, service, runner, said, lines, clock = comments
    runner.current = Foreground("VALORANT", True)
    clock.now += 601
    service.check()
    assert said == []
    assert len(lines) == 1


def test_talking_resets_the_wait(comments):
    bus, service, runner, said, _, clock = comments
    runner.current = Foreground("Vídeo - YouTube", False)
    clock.now += 601
    bus.user_message.emit("hola")
    service.check()
    assert said == []


def test_turning_comments_off_stops_them(comments):
    bus, service, runner, said, _, clock = comments
    runner.current = Foreground("Vídeo - YouTube", False)
    bus.comments_enabled_requested.emit(False)
    clock.now += 601
    service.check()
    assert said == []


def test_game_lines_format_with_the_name():
    assert all("{" not in line.format(juego="X").replace("X", "") for line in load_game_lines())


def test_busy_conversation_retries_the_comment_later(comments, settings, tmp_path):
    _, service, runner, _, _, clock = comments
    service._comment = lambda title: False
    runner.current = Foreground("Vídeo - YouTube", False)
    clock.now += 601
    service.check()
    assert service._last_title == ""


def test_comment_appears_labelled_in_the_chat(qapp):
    bus = EventBus()
    window = ChatWindow(bus)
    bus.assistant_token.emit("Qué buen vídeo.")
    bus.assistant_done.emit()
    bus.assistant_token.emit("Otro.")
    bus.assistant_done.emit()
    assert window._log.toPlainText() == "Teto: Qué buen vídeo.\n\nTeto: Otro.\n\n"
    window.close()


def test_spontaneous_comment_stays_out_of_the_conversation(desktop):
    bus, service, _, seen, record, *_ = desktop
    assert service.comment("Vídeo - YouTube")
    pump(lambda: record["done"] == 1)
    assert "YouTube" in seen[0][0][-1]["content"]
    bus.user_message.emit("Hola")
    pump(lambda: record["done"] == 2)
    assert len(seen[1][0]) == 2
