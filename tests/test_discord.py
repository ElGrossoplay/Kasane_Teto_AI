import time
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtGui import QGuiApplication

import kasane_teto.core.conversation as conversation
from kasane_teto.core.events import EventBus
from kasane_teto.interface.discord_window import DiscordWindow
from kasane_teto.memory.knowledge import KnowledgeBase
from kasane_teto.tools import discord_rpc
from kasane_teto.tools.commands import (
    CHAT_MESSAGE,
    CHAT_OPEN,
    USUAL_CHANNEL,
    VOICE_JOIN,
    VOICE_LEAVE,
    Command,
    parse_command,
)
from kasane_teto.tools.discord_rpc import (
    OP_CLOSE,
    OP_FRAME,
    DiscordError,
    DiscordVoice,
    RpcError,
)
from kasane_teto.tools.registry import ActionRejected, ToolRegistry, WindowsRunner
from kasane_teto.tools.secure_store import SecureStore, protect, unprotect
from kasane_teto.tools.windows_control import Foreground, Window

GUILDS = [{"id": "1", "name": "Minecraft"}, {"id": "2", "name": "Amigos"}]
CHANNELS = {
    "1": [
        {"id": "10", "name": "chat", "type": 0},
        {"id": "11", "name": "General", "type": 2},
        {"id": "12", "name": "Survival", "type": 2},
    ],
    "2": [{"id": "21", "name": "General", "type": 2}, {"id": "22", "name": "Sala Gamer", "type": 2}],
}


class FakeDiscord:
    """Cliente de Discord simulado: responde a la misma secuencia de la documentación."""

    instances = []
    fail_handshake = False
    errors = {}

    def __init__(self):
        self.commands = []
        self.pending = []
        FakeDiscord.instances.append(self)

    @classmethod
    def connect(cls):
        return cls()

    def send(self, op, payload):
        if op == 0:
            if FakeDiscord.fail_handshake:
                self.pending.append((OP_CLOSE, {"code": 4000, "message": "Invalid Client ID"}))
            else:
                self.pending.append((OP_FRAME, {"evt": "READY", "data": {"v": 1}}))
            return
        self.commands.append(payload)
        cmd, nonce = payload["cmd"], payload["nonce"]
        if cmd in FakeDiscord.errors:
            data = {"code": FakeDiscord.errors[cmd], "message": "no"}
            self.pending.append((OP_FRAME, {"cmd": cmd, "evt": "ERROR", "nonce": nonce, "data": data}))
            return
        data = {
            "AUTHORIZE": {"code": "codigo"},
            "AUTHENTICATE": {"user": {"username": "diego"}},
            "GET_GUILDS": {"guilds": GUILDS},
            "SELECT_VOICE_CHANNEL": {"id": "11"},
        }.get(cmd, {})
        if cmd == "GET_CHANNELS":
            data = {"channels": CHANNELS[payload["args"]["guild_id"]]}
        self.pending.append((OP_FRAME, {"evt": "NOISE", "nonce": "otro"}))
        self.pending.append((OP_FRAME, {"cmd": cmd, "nonce": nonce, "data": data}))

    def receive(self, timeout):
        return self.pending.pop(0)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def reset():
    FakeDiscord.instances = []
    FakeDiscord.fail_handshake = False
    FakeDiscord.errors = {}


def commands():
    return [c for d in FakeDiscord.instances for c in d.commands]


def named(cmd):
    return [c for c in commands() if c["cmd"] == cmd]


@pytest.fixture
def http_calls():
    return []


@pytest.fixture
def http(http_calls):
    def handler(request):
        http_calls.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(
            200, json={"access_token": "tok", "refresh_token": "ref", "expires_in": 604800}
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def discord(tmp_path, http):
    voice = DiscordVoice(SecureStore(tmp_path / "discord.bin"), FakeDiscord, http)
    voice.authorize("123", "secreto")
    return voice


def test_secrets_are_encrypted_on_disk(tmp_path):
    path = tmp_path / "s.bin"
    store = SecureStore(path)
    store.save({"client_secret": "muysecreto"})
    assert b"muysecreto" not in path.read_bytes()
    assert store.load() == {"client_secret": "muysecreto"}


def test_protect_round_trip_with_accents():
    data = "contraseña".encode()
    assert unprotect(protect(data)) == data


def test_corrupt_secret_file_is_ignored(tmp_path):
    path = tmp_path / "s.bin"
    path.write_bytes(b"basura")
    assert SecureStore(path).load() == {}


def test_authorize_follows_the_documented_flow(discord, http_calls):
    assert named("AUTHORIZE")[0]["args"]["scopes"] == ["rpc", "identify"]
    form = http_calls[0]
    assert form["code"] == "codigo"
    assert form["client_secret"] == "secreto"
    assert form["redirect_uri"] == "http://127.0.0.1"
    assert discord.is_configured


def test_only_voice_channels_are_listed(discord):
    assert {c.id for c in discord.voice_channels()} == {"11", "12", "21", "22"}


def test_channels_are_cached(discord):
    before = len(named("GET_GUILDS"))
    discord.voice_channels()
    assert len(named("GET_GUILDS")) == before


@pytest.mark.parametrize(
    ("target", "channel"),
    [
        ("Survival", "12"),
        ("survival de minecraft", "12"),
        ("sala gamer", "22"),
        ("sala gamer de amigos", "22"),
        ("sala gamel", "22"),
        ("general de amigos", "21"),
        ("minecraft", "11"),
    ],
)
def test_channel_is_found_by_how_it_is_said(discord, target, channel):
    assert discord.find(target).id == channel


def test_same_name_in_two_servers_asks_which(discord):
    with pytest.raises(DiscordError, match="varios"):
        discord.find("General")


def test_unknown_channel_is_refused(discord):
    with pytest.raises(DiscordError, match="No encuentro"):
        discord.find("zzzzzz")


def test_join_uses_the_official_command_and_remembers(discord):
    channel = discord.find("Survival")
    discord.join(channel)
    args = named("SELECT_VOICE_CHANNEL")[-1]["args"]
    assert args["channel_id"] == "12"
    assert named("AUTHENTICATE")
    assert discord.favorite().id == "12"


def test_favorite_needs_a_previous_channel(discord):
    with pytest.raises(DiscordError, match="de siempre"):
        discord.favorite()


def test_leave_sends_null_channel(discord):
    discord.leave()
    assert named("SELECT_VOICE_CHANNEL")[-1]["args"]["channel_id"] is None


def test_expired_token_is_refreshed(discord, http_calls, tmp_path):
    store = SecureStore(tmp_path / "discord.bin")
    store.save({**store.load(), "expires_at": 0})
    discord.leave()
    assert http_calls[-1]["grant_type"] == "refresh_token"


def test_discord_closed_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_rpc, "PIPE_TEMPLATE", str(tmp_path / "nada{}"))
    with pytest.raises(DiscordError, match="no está abierto"):
        discord_rpc.PipeTransport.connect()


def test_rejected_application_is_explained(tmp_path, http):
    FakeDiscord.fail_handshake = True
    voice = DiscordVoice(SecureStore(tmp_path / "d.bin"), FakeDiscord, http)
    with pytest.raises(DiscordError, match="Invalid Client ID"):
        voice.authorize("mal", "secreto")
    assert not voice.is_configured


def test_refused_authorization_saves_nothing(tmp_path, http):
    FakeDiscord.errors = {"AUTHORIZE": 5000}
    voice = DiscordVoice(SecureStore(tmp_path / "d.bin"), FakeDiscord, http)
    with pytest.raises(RpcError):
        voice.authorize("123", "secreto")
    assert not (tmp_path / "d.bin").exists()


def test_bad_secret_is_explained(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={}))
    voice = DiscordVoice(SecureStore(tmp_path / "d.bin"), FakeDiscord, transport)
    with pytest.raises(DiscordError, match="Revisa"):
        voice.authorize("123", "mal")


def test_forget_erases_the_file(discord, tmp_path):
    discord.forget()
    assert not (tmp_path / "discord.bin").exists()
    assert not discord.is_configured


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("Entra al canal Survival", "Survival"),
        ("Métete al canal de voz Survival de Minecraft", "Survival de Minecraft"),
        ("Únete a Sala Gamer", "Sala Gamer"),
        ("Conéctate a General de Amigos", "General de Amigos"),
        ("Entra al servidor Minecraft", "Minecraft"),
        ("Entra a mi canal de siempre", USUAL_CHANNEL),
        ("Métete al canal", USUAL_CHANNEL),
    ],
)
def test_join_orders(text, target):
    assert parse_command(text) == Command(VOICE_JOIN, target)


@pytest.mark.parametrize(
    "text", ["Sal del canal", "Sal del canal de voz", "Desconéctate", "Cuelga", "Salte de Discord"]
)
def test_leave_orders(text):
    assert parse_command(text) == Command(VOICE_LEAVE)


@pytest.mark.parametrize(
    "text",
    ["Entra en detalle sobre Miku", "Entra un poco más", "Hoy salí del trabajo", "¿Cómo entro al canal?"],
)
def test_conversation_is_not_a_voice_order(text):
    command = parse_command(text)
    assert command is None or command.kind not in (VOICE_JOIN, VOICE_LEAVE)


def pump(condition, timeout_ms=3000):
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        QCoreApplication.processEvents()
        time.sleep(0.002)
    assert condition()


class FakeResources:
    def set_busy(self, busy):
        pass


@pytest.fixture
def service(qapp, settings, tmp_path, discord):
    settings.set("tools.enabled", True)
    tools = ToolRegistry(settings, tmp_path / "a.log", None, {}, discord)
    bus = EventBus()
    record = {"done": 0, "tokens": [], "actions": []}
    bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
    bus.assistant_token.connect(record["tokens"].append)
    bus.action_proposed.connect(record["actions"].append)
    item = conversation.ConversationService(
        bus, FakeResources(), settings, KnowledgeBase([]), tools=tools
    )
    return bus, item, discord, record


def say(bus, record, text):
    done = record["done"]
    bus.user_message.emit(text)
    pump(lambda: record["done"] == done + 1)


def test_joining_goes_straight_in(service):
    bus, _, _, record = service
    say(bus, record, "Entra al canal Survival")
    assert record["actions"] == []
    assert named("SELECT_VOICE_CHANNEL")[-1]["args"]["channel_id"] == "12"
    assert record["tokens"][-1] == "Dentro de Survival."


def test_joining_asks_if_the_confirmation_option_is_on(service, settings):
    bus, _, _, record = service
    settings.set("tools.confirm", True)
    say(bus, record, "Entra al canal Survival")
    assert record["actions"]
    assert not named("SELECT_VOICE_CHANNEL")
    say(bus, record, "ti")
    assert named("SELECT_VOICE_CHANNEL")[-1]["args"]["channel_id"] == "12"


def test_no_stays_out_with_the_confirmation_option(service, settings):
    bus, _, _, record = service
    settings.set("tools.confirm", True)
    say(bus, record, "Entra al canal Survival")
    say(bus, record, "no")
    assert not named("SELECT_VOICE_CHANNEL")


def test_leaving_does_not_ask(service):
    bus, _, _, record = service
    say(bus, record, "Sal del canal")
    assert record["actions"] == []
    assert record["tokens"][-1] == "He salido del canal."


def test_without_setup_explains_what_to_do(qapp, settings, tmp_path, http):
    settings.set("tools.enabled", True)
    voice = DiscordVoice(SecureStore(tmp_path / "vacío.bin"), FakeDiscord, http)
    tools = ToolRegistry(settings, tmp_path / "a.log", None, {}, voice)
    bus = EventBus()
    tokens = []
    bus.assistant_token.connect(tokens.append)
    service = conversation.ConversationService(
        bus, FakeResources(), settings, KnowledgeBase([]), tools=tools
    )
    bus.user_message.emit("Entra al canal Survival")
    pump(lambda: tokens)
    assert "Configuración" in tokens[0]
    assert service is not None


def test_window_masks_the_secret_and_connects(qapp, tmp_path, http):
    voice = DiscordVoice(SecureStore(tmp_path / "w.bin"), FakeDiscord, http)
    window = DiscordWindow(voice)
    assert window._secret.echoMode() == window._secret.EchoMode.Password
    window._client_id.setText("123")
    window._secret.setText("secreto")
    window._connect.click()
    pump(lambda: "Conectado" in window._status.text())
    assert window._secret.text() == ""
    assert "4 canales" in window._status.text()
    window.close()


def test_window_requires_both_fields(qapp, tmp_path, http):
    voice = DiscordVoice(SecureStore(tmp_path / "w.bin"), FakeDiscord, http)
    window = DiscordWindow(voice)
    window._connect.click()
    assert "Faltan" in window._status.text()
    window.close()


CHAT_ID = "123456789012345678"
OTHER_CHAT_ID = "223456789012345678"


class FakeRunner(WindowsRunner):
    """Las pruebas no deben tocar el Discord ni las ventanas del equipo real."""

    def __init__(self):
        self.windows = [Window(7, "Amigos - Discord")]
        self.current = Foreground("Bloc de notas", False)
        self.focused = []
        self.links = []

    def list_windows(self):
        return self.windows

    def foreground(self):
        return self.current

    def focus_window(self, handle):
        self.focused.append(handle)

    def open_link(self, link):
        self.links.append(link)


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def tools(settings, tmp_path, discord, runner):
    discord.add_contact("Pablo", CHAT_ID)
    return ToolRegistry(settings, tmp_path / "a.log", runner, {}, discord)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Abre el chat de Pablo", Command(CHAT_OPEN, "Pablo")),
        ("Ábreme mi chat con Pablo Pérez", Command(CHAT_OPEN, "Pablo Pérez")),
        ("Abre la conversación con mi amigo Pablo", Command(CHAT_OPEN, "Pablo")),
        ("Métete al chat de Pablo", Command(CHAT_OPEN, "Pablo")),
        ("Abre el chat de Pablo en Discord.", Command(CHAT_OPEN, "Pablo")),
        ("Abre mi chat de Discord con Pablo", Command(CHAT_OPEN, "Pablo")),
        ("Mándale un mensaje a Pablo", Command(CHAT_OPEN, "Pablo")),
        ("Dile a Pablo que llego tarde", Command(CHAT_MESSAGE, "Pablo", detail="llego tarde")),
        ("Oye Teto, dile a Pablo Pérez que llego", Command(CHAT_MESSAGE, "Pablo Pérez", detail="llego")),
        ("Escríbele a mi amiga Ana: hola", Command(CHAT_MESSAGE, "Ana", detail="hola")),
        ("Dile a Pablo si viene hoy", Command(CHAT_MESSAGE, "Pablo", detail="si viene hoy")),
        (
            "Mándale un mensaje a Pablo diciendo que llego tarde",
            Command(CHAT_MESSAGE, "Pablo", detail="llego tarde"),
        ),
        (
            "Mándale a Pablo un mensaje que diga que llego tarde",
            Command(CHAT_MESSAGE, "Pablo", detail="llego tarde"),
        ),
        (
            "Quiero que le mandes un mensaje a Pablo que diga hola",
            Command(CHAT_MESSAGE, "Pablo", detail="hola"),
        ),
        (
            "Escríbele por Discord a Pablo que llego tarde",
            Command(CHAT_MESSAGE, "Pablo", detail="llego tarde"),
        ),
        (
            "Abre el chat de Pablo y dile que llego tarde",
            Command(CHAT_MESSAGE, "Pablo", detail="llego tarde"),
        ),
    ],
)
def test_chat_orders(text, expected):
    assert parse_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Dime un chiste",
        "Escribe un poema en el bloc de notas",
        "Escribe una carta a mi abuela en Word",
        "Abre Discord y dime un chiste",
        "¿Qué le dirías a Pablo?",
        "Dile que sí",
    ],
)
def test_other_sentences_are_not_chat_orders(text):
    command = parse_command(text)
    assert command is None or command.kind not in (CHAT_OPEN, CHAT_MESSAGE)


def test_voice_channels_are_not_chats():
    assert parse_command("Entra al canal Pablo") == Command(VOICE_JOIN, "Pablo")


@pytest.mark.parametrize(
    "chat",
    [CHAT_ID, f" {CHAT_ID} ", f"https://discord.com/channels/@me/{CHAT_ID}"],
)
def test_contact_accepts_the_id_or_the_link(discord, chat):
    assert discord.add_contact("Pablo", chat).chat_id == CHAT_ID


@pytest.mark.parametrize(("name", "chat"), [("", CHAT_ID), ("Pablo", ""), ("Pablo", "hola"), ("Pablo", "123")])
def test_bad_contacts_are_refused(discord, name, chat):
    with pytest.raises(DiscordError, match="Faltan"):
        discord.add_contact(name, chat)
    assert discord.contacts() == []


def test_same_name_replaces_the_contact(discord):
    discord.add_contact("Pablo", CHAT_ID)
    discord.add_contact("pablo", OTHER_CHAT_ID)
    assert [c.chat_id for c in discord.contacts()] == [OTHER_CHAT_ID]


def test_contacts_are_encrypted_on_disk(discord, tmp_path):
    discord.add_contact("Pablo", CHAT_ID)
    data = (tmp_path / "discord.bin").read_bytes()
    assert b"Pablo" not in data
    assert CHAT_ID.encode() not in data


def test_reconnecting_keeps_contacts(discord):
    discord.add_contact("Pablo", CHAT_ID)
    discord.authorize("123", "otro")
    assert [c.name for c in discord.contacts()] == ["Pablo"]


def test_forgetting_erases_contacts(discord):
    discord.add_contact("Pablo", CHAT_ID)
    discord.forget()
    assert discord.contacts() == []


@pytest.mark.parametrize("target", ["Pablo", "pablo", "Pavlo"])
def test_contact_is_found_by_how_it_is_said(discord, target):
    discord.add_contact("Pablo", CHAT_ID)
    discord.add_contact("Ana", OTHER_CHAT_ID)
    assert discord.find_contact(target).chat_id == CHAT_ID


def test_unknown_contact_is_explained(discord):
    with pytest.raises(DiscordError, match="No tengo a Zoe"):
        discord.find_contact("Zoe")


def test_similar_contacts_ask_which(discord):
    discord.add_contact("Marta G", CHAT_ID)
    discord.add_contact("Marta R", OTHER_CHAT_ID)
    with pytest.raises(DiscordError, match="A quién"):
        discord.find_contact("Marta X")


def test_opening_a_chat_uses_the_official_command(tools, runner):
    assert tools.open_chat("Pablo") == "Pablo"
    args = named("SELECT_TEXT_CHANNEL")[-1]["args"]
    assert args["channel_id"] == CHAT_ID
    assert runner.focused == [7]
    assert runner.links == []


def test_browser_tab_is_not_discord(tools, runner):
    runner.windows = [Window(8, "Discord - Google Chrome")]
    tools.open_chat("Pablo")
    assert runner.focused == []
    assert runner.links == [f"discord://-/channels/@me/{CHAT_ID}"]


def test_game_in_front_keeps_the_focus(tools, runner):
    runner.current = Foreground("Juego", True)
    tools.open_chat("Pablo")
    assert named("SELECT_TEXT_CHANNEL")
    assert runner.focused == []
    assert runner.links == []


def test_discord_hidden_in_the_tray_opens_by_link(tools, runner):
    runner.windows = []
    tools.open_chat("Pablo")
    assert runner.links == [f"discord://-/channels/@me/{CHAT_ID}"]


def test_closed_discord_opens_by_link(tools, runner, monkeypatch):
    def closed():
        raise DiscordError("Discord no está abierto.")

    monkeypatch.setattr(FakeDiscord, "connect", staticmethod(closed))
    assert tools.open_chat("Pablo") == "Pablo"
    assert runner.links == [f"discord://-/channels/@me/{CHAT_ID}"]


def test_rejected_chat_id_is_explained(tools, runner):
    FakeDiscord.errors = {"SELECT_TEXT_CHANNEL": 4005}
    with pytest.raises(ActionRejected, match="ID del canal"):
        tools.open_chat("Pablo")
    assert runner.links == []


class FakeProcess:
    base_url = "http://127.0.0.1:1"
    api_key = ""


class DraftingResources(FakeResources):
    def ensure_loaded(self, vision=False):
        return FakeProcess()


class FakeClient:
    finish_reason = "stop"
    last_messages = None
    answer = "[neutral] Oye, llego tarde."

    def __init__(self, base_url, api_key):
        pass

    def stream_chat(self, messages, params, cancel):
        FakeClient.last_messages = messages
        yield FakeClient.answer


@pytest.fixture
def chat_service(qapp, settings, tools, monkeypatch):
    monkeypatch.setattr(conversation, "LLMClient", FakeClient)
    settings.set("tools.enabled", True)
    bus = EventBus()
    record = {"done": 0, "tokens": []}
    bus.assistant_done.connect(lambda: record.__setitem__("done", record["done"] + 1))
    bus.assistant_token.connect(record["tokens"].append)
    item = conversation.ConversationService(
        bus, DraftingResources(), settings, KnowledgeBase([]), tools=tools
    )
    return bus, item, record


def test_open_chat_goes_straight_in(chat_service):
    bus, _, record = chat_service
    say(bus, record, "Abre el chat de Pablo")
    assert named("SELECT_TEXT_CHANNEL")[-1]["args"]["channel_id"] == CHAT_ID
    assert record["tokens"][-1] == "Chat con Pablo abierto."


def test_message_is_drafted_copied_and_never_sent(chat_service, qapp):
    bus, _, record = chat_service
    QGuiApplication.clipboard().clear()
    say(bus, record, "Dile a Pablo que llego tarde")
    pump(lambda: QGuiApplication.clipboard().text() == "Oye, llego tarde.")
    reply = "".join(record["tokens"])
    assert "Oye, llego tarde." in reply
    assert "envíalo tú" in reply
    assert named("SELECT_TEXT_CHANNEL")[-1]["args"]["channel_id"] == CHAT_ID
    assert {c["cmd"] for c in commands()} <= {
        "AUTHORIZE", "AUTHENTICATE", "GET_GUILDS", "GET_CHANNELS", "SELECT_TEXT_CHANNEL"
    }


def test_message_prompt_carries_only_what_was_asked(chat_service):
    bus, _, record = chat_service
    say(bus, record, "Dile a Pavlo que llego tarde")
    prompt = FakeClient.last_messages[-1]["content"]
    assert "a Pablo por chat" in prompt
    assert prompt.endswith("llego tarde")


def test_quotes_around_the_draft_are_removed(chat_service, monkeypatch):
    bus, _, record = chat_service
    monkeypatch.setattr(FakeClient, "answer", '[neutral] Aquí tienes:\n"Hola, Pablo."')
    say(bus, record, "Dile a Pablo que hola")
    pump(lambda: QGuiApplication.clipboard().text() == "Hola, Pablo.")


def test_unknown_contact_does_not_load_the_model(chat_service, monkeypatch):
    bus, _, record = chat_service
    monkeypatch.setattr(FakeClient, "last_messages", None)
    say(bus, record, "Dile a Zoe que hola")
    assert "No tengo a Zoe" in record["tokens"][-1]
    assert FakeClient.last_messages is None


def test_chat_failure_still_leaves_the_message_copied(chat_service):
    bus, _, record = chat_service
    FakeDiscord.errors = {"SELECT_TEXT_CHANNEL": 4005}
    say(bus, record, "Dile a Pablo que llego tarde")
    pump(lambda: QGuiApplication.clipboard().text() == "Oye, llego tarde.")
    reply = "".join(record["tokens"])
    assert "no pude abrir el chat" in reply
    assert "Oye, llego tarde." in reply


def test_window_adds_and_removes_contacts(qapp, discord):
    window = DiscordWindow(discord)
    window._contact_name.setText("Pablo")
    window._contact_chat.setText(CHAT_ID)
    window._add_contact.click()
    assert window._contacts.count() == 1
    assert window._contact_chat.text() == ""
    window._contacts.setCurrentRow(0)
    window._remove_contact.click()
    assert window._contacts.count() == 0
    assert discord.contacts() == []
    window.close()


def test_window_explains_a_bad_contact(qapp, discord):
    window = DiscordWindow(discord)
    window._contact_name.setText("Pablo")
    window._contact_chat.setText("no es un id")
    window._add_contact.click()
    assert "Faltan" in window._status.text()
    assert window._contacts.count() == 0
    window.close()


def test_no_automation_of_the_discord_interface():
    """Regla de Discord: nada de simular clics o teclado, ni usar el token de sesión."""
    for module in (discord_rpc, conversation):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "SendInput" not in source
        assert "keybd_event" not in source
    source = Path(discord_rpc.__file__).read_text(encoding="utf-8")
    assert "leveldb" not in source.casefold()
    assert "discord.com/api/v" not in source
    assert "CREATE_MESSAGE" not in source
