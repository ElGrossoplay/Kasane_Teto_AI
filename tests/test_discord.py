import time
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer

import kasane_teto.core.conversation as conversation
from kasane_teto.core.events import EventBus
from kasane_teto.interface.discord_window import DiscordWindow
from kasane_teto.memory.knowledge import KnowledgeBase
from kasane_teto.tools import discord_rpc
from kasane_teto.tools.commands import USUAL_CHANNEL, VOICE_JOIN, VOICE_LEAVE, Command, parse_command
from kasane_teto.tools.discord_rpc import (
    OP_CLOSE,
    OP_FRAME,
    DiscordError,
    DiscordVoice,
    RpcError,
)
from kasane_teto.tools.registry import ToolRegistry
from kasane_teto.tools.secure_store import SecureStore, protect, unprotect

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


def test_joining_always_asks_even_without_confirmation(service):
    bus, _, _, record = service
    say(bus, record, "Entra al canal Survival")
    assert "micrófono" in record["actions"][0]
    assert not [c for c in named("SELECT_VOICE_CHANNEL")]


def test_yes_joins_the_channel(service):
    bus, _, _, record = service
    say(bus, record, "Entra al canal Survival")
    say(bus, record, "sí")
    assert named("SELECT_VOICE_CHANNEL")[-1]["args"]["channel_id"] == "12"
    assert record["tokens"][-1] == "Dentro de Survival."


def test_no_stays_out(service):
    bus, _, _, record = service
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


def test_no_automation_of_the_discord_interface():
    """Regla de Discord: nada de simular clics o teclado, ni usar el token de sesión."""
    source = Path(discord_rpc.__file__).read_text(encoding="utf-8")
    assert "SendInput" not in source
    assert "leveldb" not in source.casefold()
    assert "discord.com/api/v" not in source
