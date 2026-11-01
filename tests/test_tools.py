import ast
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

import kasane_teto.core.conversation as conversation
import kasane_teto.tools.registry as registry_module
from kasane_teto.core.events import EventBus
from kasane_teto.interface.apps_window import AppsWindow
from kasane_teto.interface.chat_window import ChatWindow
from kasane_teto.memory.knowledge import KnowledgeBase
from kasane_teto.tools.commands import (
    INFO,
    OPEN_APP,
    OPEN_FILE,
    OPEN_FOLDER,
    OPEN_URL,
    WEB_SEARCH,
    Command,
    parse_command,
)
from kasane_teto.tools.registry import (
    FORBIDDEN_PROGRAMS,
    ActionRejected,
    ToolRegistry,
    WindowsRunner,
    system_info,
    validate_program,
    validate_url,
)

SOURCE = Path(conversation.__file__).parents[1]


@pytest.mark.parametrize(
    ("text", "kind", "target"),
    [
        ("Abre Discord", OPEN_APP, "Discord"),
        ("Teto, abre la calculadora, por favor.", OPEN_APP, "calculadora"),
        ("¿Puedes abrir el bloc de notas?", OPEN_APP, "bloc de notas"),
        ("Ábreme Spotify", OPEN_APP, "Spotify"),
        ("Abre la carpeta de descargas", OPEN_FOLDER, "descargas"),
        ("Abre mis documentos", OPEN_FOLDER, "documentos"),
        ("Abre el escritorio", OPEN_FOLDER, "escritorio"),
        ("Abre las fotos", OPEN_FOLDER, "imagenes"),
        ("Abre el archivo informe.pdf", OPEN_FILE, "informe.pdf"),
        ("Abre la foto gato", OPEN_FILE, "gato"),
        ("Abre notas.txt", OPEN_FILE, "notas.txt"),
        ("Abre virus.exe", OPEN_FILE, "virus.exe"),
        ("Abre youtube.com", OPEN_URL, "youtube.com"),
        ("Abre youtube punto com", OPEN_URL, "youtube.com"),
        ("Abre https://vocadb.net/S/1", OPEN_URL, "https://vocadb.net/S/1"),
        ("Busca recetas de pan en Internet", WEB_SEARCH, "recetas de pan"),
        ("búscame gatos en Google", WEB_SEARCH, "gatos"),
        ("¿Qué hora es?", INFO, "hora"),
        ("¿Qué día es hoy?", INFO, "fecha"),
        ("¿Cuánta RAM estoy usando?", INFO, "memoria"),
        ("¿Cómo va la CPU?", INFO, "cpu"),
        ("¿Cuánto espacio me queda?", INFO, "disco"),
        ("¿Cuánta batería queda?", INFO, "bateria"),
    ],
)
def test_clear_orders_are_recognised(text, kind, target):
    assert parse_command(text) == Command(kind, target)


@pytest.mark.parametrize(
    "text",
    [
        "Hola, ¿cómo estás?",
        "Explícame qué es la memoria RAM.",
        "¿Quién es Kikuo?",
        "Mi amigo abre la puerta",
        "No abras eso",
        "busca en internet Tetoris",
        "Háblame de Vocaloid",
    ],
)
def test_conversation_is_not_an_order(text):
    assert parse_command(text) is None


@pytest.fixture
def folders(tmp_path):
    paths = {}
    for name in ("documentos", "descargas", "imagenes", "musica", "videos", "escritorio"):
        paths[name] = tmp_path / name
        paths[name].mkdir()
    return paths


class FakeRunner:
    def __init__(self, error=None):
        self.started = []
        self.opened = []
        self.urls = []
        self.error = error

    def start_program(self, path):
        if self.error:
            raise self.error
        self.started.append(path)

    def open_path(self, path):
        self.opened.append(path)

    def open_url(self, url):
        self.urls.append(url)


@pytest.fixture
def tools(settings, tmp_path, folders):
    return ToolRegistry(settings, tmp_path / "logs" / "actions.log", FakeRunner(), folders)


@pytest.fixture
def fake_app(tmp_path):
    path = tmp_path / "programa.exe"
    path.write_bytes(b"MZ")
    return path


def test_catalog_app_is_opened(tools, settings, fake_app):
    settings.set("tools.apps", {"discord": str(fake_app)})
    action = tools.prepare(Command(OPEN_APP, "Discord"))
    assert action.summary == "Voy a abrir discord"
    tools.run(action)
    assert tools._runner.started == [fake_app]


@pytest.mark.parametrize("heard", ["Discort", "discor", "DISCORD"])
def test_catalog_tolerates_misheard_names(tools, settings, fake_app, heard):
    settings.set("tools.apps", {"discord": str(fake_app)})
    assert tools.prepare(Command(OPEN_APP, heard)).resolved == str(fake_app)


def test_builtin_app_is_found_on_the_system(tools):
    assert tools.prepare(Command(OPEN_APP, "calculadora")).resolved.lower().endswith("calc.exe")


@pytest.mark.parametrize("name", ["valorant", "cmd", "powershell", "regedit", "mi novia"])
def test_app_outside_the_catalog_is_rejected(tools, name):
    with pytest.raises(ActionRejected, match="no está en mi lista"):
        tools.prepare(Command(OPEN_APP, name))


@pytest.mark.parametrize("program", sorted(FORBIDDEN_PROGRAMS))
def test_shells_are_rejected_even_inside_the_catalog(tools, settings, tmp_path, program):
    path = tmp_path / f"{program}.exe"
    path.write_bytes(b"MZ")
    settings.set("tools.apps", {"miapp": str(path)})
    with pytest.raises(ActionRejected):
        tools.prepare(Command(OPEN_APP, "miapp"))


@pytest.mark.parametrize("suffix", [".bat", ".cmd", ".ps1", ".lnk", ".vbs", ".txt"])
def test_only_exe_programs_are_valid(tmp_path, suffix):
    path = tmp_path / f"programa{suffix}"
    path.write_bytes(b"x")
    with pytest.raises(ActionRejected):
        validate_program(path)


def test_program_deleted_after_confirmation_is_not_run(tools, settings, fake_app):
    settings.set("tools.apps", {"discord": str(fake_app)})
    action = tools.prepare(Command(OPEN_APP, "discord"))
    fake_app.unlink()
    with pytest.raises(ActionRejected):
        tools.run(action)
    assert tools._runner.started == []


def test_program_is_started_without_arguments_or_shell(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(registry_module.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    WindowsRunner().start_program(tmp_path / "a.exe")
    assert calls[0][0] == [str(tmp_path / "a.exe")]
    assert "shell" not in calls[0][1]


def test_known_folder_is_opened(tools, folders):
    tools.run(tools.prepare(Command(OPEN_FOLDER, "descargas")))
    assert tools._runner.opened == [folders["descargas"]]


@pytest.mark.parametrize("name", ["informe.pdf", "INFORME.PDF", "informe"])
def test_safe_file_is_found_by_name(tools, folders, name):
    path = folders["documentos"] / "informe.pdf"
    path.write_text("x")
    tools.run(tools.prepare(Command(OPEN_FILE, name)))
    assert tools._runner.opened == [path]


@pytest.mark.parametrize(
    "name",
    ["virus.exe", "script.bat", "acceso.lnk", "macro.ps1", "pagina.hta", "web.url", "foto.png.exe",
     "libro.docm"],
)
def test_dangerous_files_are_rejected_even_if_they_exist(tools, folders, name):
    (folders["descargas"] / name).write_bytes(b"x")
    with pytest.raises(ActionRejected):
        tools.prepare(Command(OPEN_FILE, name))


def test_stem_does_not_match_a_dangerous_file(tools, folders):
    (folders["descargas"] / "informe.exe").write_bytes(b"x")
    with pytest.raises(ActionRejected, match="No encuentro"):
        tools.prepare(Command(OPEN_FILE, "informe"))


@pytest.mark.parametrize(
    "name",
    ["../secreto.txt", "..\\secreto.txt", "C:\\Windows\\win.ini", "a.txt:oculto", "*.txt", ""],
)
def test_paths_and_tricks_are_rejected(tools, name):
    with pytest.raises(ActionRejected):
        tools.prepare(Command(OPEN_FILE, name))


def test_file_outside_known_folders_is_not_found(tools, tmp_path):
    (tmp_path / "fuera.txt").write_text("x")
    with pytest.raises(ActionRejected, match="No encuentro"):
        tools.prepare(Command(OPEN_FILE, "fuera.txt"))


def test_file_inside_a_subfolder_is_not_opened(tools, folders):
    sub = folders["documentos"] / "sub"
    sub.mkdir()
    (sub / "dentro.txt").write_text("x")
    with pytest.raises(ActionRejected, match="No encuentro"):
        tools.prepare(Command(OPEN_FILE, "dentro.txt"))


def test_ambiguous_file_is_not_guessed(tools, folders):
    (folders["documentos"] / "foto.png").write_text("x")
    (folders["imagenes"] / "foto.png").write_text("x")
    with pytest.raises(ActionRejected, match="varios"):
        tools.prepare(Command(OPEN_FILE, "foto.png"))


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com",
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "ftp://servidor.com",
        "https://usuario:clave@banco.com",
        "https://youtube.com@malo.com",
        "https://localhost",
        "https://192.168.1.1",
        "https://127.0.0.1:8080",
        "https://sinpunto",
    ],
)
def test_unsafe_links_are_rejected(url):
    with pytest.raises(ActionRejected):
        validate_url(url)


def test_bare_domain_becomes_https(tools):
    action = tools.prepare(Command(OPEN_URL, "youtube.com"))
    tools.run(action)
    assert tools._runner.urls == ["https://youtube.com"]


def test_search_is_encoded_and_opened(tools):
    tools.run(tools.prepare(Command(WEB_SEARCH, "recetas de pan & sal")))
    assert tools._runner.urls == ["https://duckduckgo.com/?q=recetas+de+pan+%26+sal"]


@pytest.mark.parametrize("query", ["mi contraseña gato123", "ana@correo.com", "600123456", "a" * 200])
def test_sensitive_or_long_search_is_rejected(tools, query):
    with pytest.raises(ActionRejected):
        tools.prepare(Command(WEB_SEARCH, query))


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("hora", "Son las"),
        ("fecha", "Hoy es"),
        ("memoria", "GB de"),
        ("cpu", "procesador"),
        ("disco", "GB libres"),
    ],
)
def test_system_info_gives_real_text(name, text):
    assert text in system_info(name)


def test_missing_battery_is_reported(monkeypatch):
    monkeypatch.setattr(registry_module.psutil, "sensors_battery", lambda: None)
    assert system_info("bateria") == "No detecto ninguna batería."


def test_unknown_kind_is_rejected(tools):
    with pytest.raises(ActionRejected):
        tools.prepare(Command("borrar", "C:\\"))


def python_sources():
    return [path for path in SOURCE.rglob("*.py")]


def test_no_shell_true_anywhere_in_the_app():
    for path in python_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword):
                assert node.arg != "shell", path


def test_app_never_lists_or_opens_other_processes():
    """Regla de anticheat: tocar procesos ajenos abriría también los de un juego."""
    forbidden = {"process_iter", "pids", "Process", "wait_procs", "OpenProcess", "EnumProcesses"}
    for path in python_sources():
        names = {
            node.attr
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute)
        }
        assert not names & forbidden, path


def test_action_log_records_each_line(tools, tmp_path):
    tools.record("app", "discord", "hecho")
    assert "app\tdiscord\thecho" in (tmp_path / "logs" / "actions.log").read_text(encoding="utf-8")


def test_real_program_starts_on_this_system():
    path = Path(shutil.which("hostname.exe"))
    WindowsRunner().start_program(path)


class FakeResources:
    def ensure_loaded(self):
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
def service(qapp, settings, tools, monkeypatch, fake_app):
    seen = []

    class FakeClient:
        finish_reason = "stop"

        def __init__(self, base_url, api_key):
            pass

        def stream_chat(self, messages, params, cancel):
            seen.append(messages)
            yield "[neutral] Abre Discord"

    monkeypatch.setattr(conversation, "LLMClient", FakeClient)
    settings.set("tools.enabled", True)
    settings.set("tools.apps", {"discord": str(fake_app)})
    bus = EventBus()
    record = {"done": 0, "tokens": [], "notices": [], "actions": []}
    bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
    bus.assistant_token.connect(record["tokens"].append)
    bus.assistant_notice.connect(record["notices"].append)
    bus.action_proposed.connect(record["actions"].append)
    item = conversation.ConversationService(
        bus, FakeResources(), settings, KnowledgeBase([]), tools=tools
    )
    return bus, item, tools, seen, record


def test_tools_are_off_by_default(settings):
    assert settings.get("tools.enabled") is False


def test_disabled_tools_never_run_and_explain_why(service, settings):
    bus, _, tools, seen, record = service
    settings.set("tools.enabled", False)
    bus.user_message.emit("Abre Discord")
    pump(lambda: record["done"] == 1)
    assert tools._runner.started == []
    assert len(seen) == 1
    assert record["notices"] == [conversation.TOOLS_OFF_NOTICE]


def test_order_waits_for_confirmation(service):
    bus, _, tools, seen, record = service
    bus.user_message.emit("Abre Discord")
    assert record["actions"] == ["Voy a abrir discord"]
    assert tools._runner.started == []
    assert seen == []
    assert "¿De acuerdo?" in record["tokens"][0]


def test_spoken_yes_runs_the_action_once(service, fake_app):
    bus, _, tools, _, record = service
    bus.user_message.emit("Abre Discord")
    bus.user_message.emit("sí")
    pump(lambda: record["done"] == 2)
    bus.user_message.emit("sí")
    pump(lambda: record["done"] == 3)
    assert tools._runner.started == [fake_app]


def test_button_yes_runs_the_action(service, fake_app):
    bus, _, tools, _, record = service
    bus.user_message.emit("Abre Discord")
    bus.action_answered.emit(True)
    pump(lambda: tools._runner.started)
    assert tools._runner.started == [fake_app]
    assert record["actions"][-1] == ""


def test_no_cancels_the_action(service):
    bus, _, tools, _, record = service
    bus.user_message.emit("Abre Discord")
    bus.user_message.emit("no")
    assert record["tokens"][-1] == conversation.ACTION_CANCELLED_REPLY
    assert tools._runner.started == []


def test_other_message_cancels_the_action(service):
    bus, _, tools, _, record = service
    bus.user_message.emit("Abre Discord")
    bus.user_message.emit("Cuéntame un chiste")
    pump(lambda: record["done"] == 2)
    bus.user_message.emit("sí")
    pump(lambda: record["done"] == 3)
    assert tools._runner.started == []


def test_stop_button_cancels_the_action(service):
    bus, _, tools, _, record = service
    bus.user_message.emit("Abre Discord")
    bus.generation_stop_requested.emit()
    assert record["actions"][-1] == ""
    bus.action_answered.emit(True)
    assert tools._runner.started == []


def test_turning_tools_off_cancels_the_action(service):
    bus, _, tools, _, record = service
    bus.user_message.emit("Abre Discord")
    bus.tools_enabled_requested.emit(False)
    bus.action_answered.emit(True)
    assert tools._runner.started == []


def test_old_confirmation_expires(service, monkeypatch):
    bus, _, tools, _, record = service
    monkeypatch.setattr(conversation, "ACTION_TIMEOUT_SECONDS", -1)
    bus.user_message.emit("Abre Discord")
    bus.user_message.emit("sí")
    assert record["tokens"][-1] == conversation.ACTION_EXPIRED_REPLY
    assert tools._runner.started == []


def test_rejected_order_is_explained_without_the_model(service):
    bus, _, _, seen, record = service
    bus.user_message.emit("Abre powershell")
    assert "no está en mi lista" in record["tokens"][0]
    assert seen == []
    assert record["actions"] == []


def test_model_text_never_triggers_an_action(service):
    bus, _, tools, seen, record = service
    bus.user_message.emit("Dime una frase")
    pump(lambda: record["done"] == 1)
    assert "".join(record["tokens"]) == "Abre Discord"
    assert record["actions"] == []
    assert tools._runner.started == []


def test_info_also_asks_first(service):
    bus, _, _, _, record = service
    bus.user_message.emit("¿Qué hora es?")
    assert record["actions"] == ["Voy a mirar la hora"]
    bus.user_message.emit("sí")
    pump(lambda: record["done"] == 2)
    assert record["tokens"][-1].startswith("Son las")


def test_failed_program_is_reported(service, tmp_path):
    bus, _, tools, _, record = service
    tools._runner.error = OSError("no arranca")
    bus.user_message.emit("Abre Discord")
    bus.user_message.emit("sí")
    pump(lambda: record["done"] == 2)
    assert record["tokens"][-1] == conversation.ACTION_FAILED_REPLY
    assert "error" in (tmp_path / "logs" / "actions.log").read_text(encoding="utf-8")


def test_every_outcome_reaches_the_log(service, tmp_path):
    bus, _, _, _, record = service
    bus.user_message.emit("Abre powershell")
    bus.user_message.emit("Abre Discord")
    bus.user_message.emit("no")
    text = (tmp_path / "logs" / "actions.log").read_text(encoding="utf-8")
    assert "powershell\trechazado" in text
    assert "Discord\tcancelado" in text


def test_chat_shows_action_bar_and_buttons_answer(qapp):
    bus = EventBus()
    window = ChatWindow(bus)
    answers = []
    bus.action_answered.connect(answers.append)
    bus.action_proposed.emit("Voy a abrir discord")
    assert not window._action_bar.isHidden()
    assert "Voy a abrir discord" in window._action.text()
    window._allow.click()
    window._deny.click()
    assert answers == [True, False]
    bus.action_proposed.emit("")
    assert window._action_bar.isHidden()
    window.close()


def test_apps_window_adds_valid_program(qapp, monkeypatch, fake_app):
    bus = EventBus()
    saved = []
    bus.allowed_apps_requested.connect(saved.append)
    window = AppsWindow(bus, {})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(fake_app), ""))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Discord", True))
    window._add()
    assert saved == [{"discord": str(fake_app)}]
    window.close()


def test_apps_window_refuses_a_shell(qapp, monkeypatch, tmp_path):
    shell = tmp_path / "cmd.exe"
    shell.write_bytes(b"MZ")
    bus = EventBus()
    saved = []
    warnings = []
    bus.allowed_apps_requested.connect(saved.append)
    window = AppsWindow(bus, {})
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(shell), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a))
    window._add()
    assert saved == []
    assert warnings
    window.close()


def test_apps_window_removes_a_program(qapp):
    bus = EventBus()
    saved = []
    bus.allowed_apps_requested.connect(saved.append)
    window = AppsWindow(bus, {"discord": "a.exe", "spotify": "b.exe"})
    window._list.setCurrentRow(0)
    window._remove()
    assert saved == [{"spotify": "b.exe"}]
    window.close()
