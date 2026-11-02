"""Control de Discord por su sistema oficial (RPC local con OAuth2), con la cuenta del usuario.

Nunca se automatiza la interfaz ni se usa el token de sesión: Discord lo prohíbe y puede cerrar
la cuenta. Solo se habla con el cliente de Discord de este equipo y con su API de OAuth2.
"""

from __future__ import annotations

import ctypes
import json
import logging
import msvcrt
import re
import struct
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

import httpx

from kasane_teto.memory.knowledge import MIN_NAME_SIMILARITY, name_key, name_similarity
from kasane_teto.tools.secure_store import SecureStore

PIPE_TEMPLATE = r"\\.\pipe\discord-ipc-{}"
PIPE_ATTEMPTS = 10
OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
RPC_VERSION = 1
SCOPES = ["rpc", "identify"]
TOKEN_URL = "https://discord.com/api/oauth2/token"
REDIRECT_URI = "http://127.0.0.1"
REPLY_TIMEOUT_SECONDS = 15.0
AUTHORIZE_TIMEOUT_SECONDS = 120.0
POLL_SECONDS = 0.05
JOIN_TIMEOUT_SECONDS = 10
CHANNELS_CACHE_SECONDS = 600.0
TOKEN_MARGIN_SECONDS = 60.0
CHANNEL_VOICE = 2
CHANNEL_STAGE = 13
ERROR_ALREADY_IN_VOICE = 5003
CHAT_LINK = "discord://-/channels/@me/{}"

_CHAT_ID = re.compile(r"\d{17,20}")
_HEADER = struct.Struct("<II")
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

log = logging.getLogger(__name__)


class DiscordError(Exception):
    """Discord no respondió como se esperaba; el texto se muestra al usuario."""


class Transport(Protocol):
    def send(self, op: int, payload: dict[str, Any]) -> None: ...
    def receive(self, timeout: float) -> tuple[int, dict[str, Any]]: ...
    def close(self) -> None: ...


class PipeTransport:
    """Tubería local con el cliente de Discord. La espera no bloquea: se puede abandonar."""

    def __init__(self, pipe: BinaryIO) -> None:
        self._pipe = pipe

    @classmethod
    def connect(cls) -> PipeTransport:
        for number in range(PIPE_ATTEMPTS):
            try:
                return cls(open(PIPE_TEMPLATE.format(number), "r+b", buffering=0))  # noqa: SIM115
            except OSError:
                continue
        raise DiscordError("Discord no está abierto.")

    def send(self, op: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self._pipe.write(_HEADER.pack(op, len(body)) + body)
        except OSError as exc:
            raise DiscordError("Se perdió la conexión con Discord.") from exc

    def _wait_data(self, deadline: float) -> None:
        handle = msvcrt.get_osfhandle(self._pipe.fileno())
        available = wintypes.DWORD()
        while time.monotonic() < deadline:
            if not _kernel32.PeekNamedPipe(
                wintypes.HANDLE(handle), None, 0, None, ctypes.byref(available), None
            ):
                raise DiscordError("Se perdió la conexión con Discord.")
            if available.value:
                return
            time.sleep(POLL_SECONDS)
        raise DiscordError("Discord tardó demasiado en responder.")

    def _read(self, size: int, deadline: float) -> bytes:
        data = b""
        while len(data) < size:
            self._wait_data(deadline)
            try:
                chunk = self._pipe.read(size - len(data))
            except OSError as exc:
                raise DiscordError("Se perdió la conexión con Discord.") from exc
            if not chunk:
                raise DiscordError("Se perdió la conexión con Discord.")
            data += chunk
        return data

    def receive(self, timeout: float) -> tuple[int, dict[str, Any]]:
        deadline = time.monotonic() + timeout
        op, size = _HEADER.unpack(self._read(_HEADER.size, deadline))
        try:
            return op, json.loads(self._read(size, deadline))
        except ValueError as exc:
            raise DiscordError("Discord envió una respuesta ilegible.") from exc

    def close(self) -> None:
        try:
            self._pipe.close()
        except OSError:
            log.debug("La tubería de Discord ya estaba cerrada")


class RpcConnection:
    def __init__(self, transport: Transport, client_id: str) -> None:
        self._transport = transport
        self._transport.send(OP_HANDSHAKE, {"v": RPC_VERSION, "client_id": client_id})
        op, data = self._transport.receive(REPLY_TIMEOUT_SECONDS)
        if op == OP_CLOSE or data.get("evt") != "READY":
            raise DiscordError(_handshake_message(data))

    def request(
        self, cmd: str, args: dict[str, Any], timeout: float = REPLY_TIMEOUT_SECONDS
    ) -> dict[str, Any]:
        nonce = str(uuid.uuid4())
        self._transport.send(OP_FRAME, {"cmd": cmd, "args": args, "nonce": nonce})
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise DiscordError("Discord tardó demasiado en responder.")
            op, data = self._transport.receive(left)
            if op == OP_CLOSE:
                raise DiscordError(_handshake_message(data))
            if data.get("nonce") != nonce:
                continue
            if data.get("evt") == "ERROR":
                error = data.get("data") or {}
                raise RpcError(int(error.get("code", 0)), str(error.get("message", "")))
            result = data.get("data")
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        self._transport.close()


class RpcError(DiscordError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"Discord rechazó la petición: {message or code}")
        self.code = code


def _handshake_message(data: dict[str, Any]) -> str:
    return f"Discord rechazó la conexión: {data.get('message', 'revisa el ID de la aplicación')}"


@dataclass(frozen=True)
class VoiceChannel:
    id: str
    name: str
    guild: str


@dataclass(frozen=True)
class Contact:
    """El RPC no da la lista de chats privados: el ID lo apunta el usuario una vez."""

    name: str
    chat_id: str


def chat_link(contact: Contact) -> str:
    return CHAT_LINK.format(contact.chat_id)


def _score(channel: VoiceChannel, target: str) -> float:
    """Admite "general", "minecraft", "general de minecraft" y nombres mal transcritos."""
    key = name_key(target)
    name, guild = name_key(channel.name), name_key(channel.guild)
    joined = max(name_similarity(key, name + guild), name_similarity(key, guild + name))
    return max(name_similarity(key, name), joined, name_similarity(key, guild) * 0.9)


class DiscordVoice:
    def __init__(
        self,
        store: SecureStore,
        connect: type[PipeTransport] | None = None,
        http: httpx.BaseTransport | None = None,
    ) -> None:
        self._store = store
        self._connect = connect or PipeTransport
        self._http = http
        self._channels: list[VoiceChannel] = []
        self._channels_at = float("-inf")

    @property
    def is_configured(self) -> bool:
        return bool(self._store.load().get("refresh_token"))

    def _exchange(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=15.0, transport=self._http) as client:
                response = client.post(TOKEN_URL, data=form)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise DiscordError("Discord rechazó los datos. Revisa el ID, el secreto y el redirect.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise DiscordError("No pude contactar con Discord.") from exc
        if not isinstance(data, dict) or "access_token" not in data:
            raise DiscordError("Discord no devolvió la autorización.")
        return data

    def _save_tokens(self, secrets: dict[str, Any], tokens: dict[str, Any]) -> dict[str, Any]:
        updated = {
            **secrets,
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", secrets.get("refresh_token", "")),
            "expires_at": time.time() + float(tokens.get("expires_in", 0)),
        }
        self._store.save(updated)
        return updated

    def authorize(self, client_id: str, client_secret: str) -> int:
        """Discord muestra su ventana de permiso; aceptarla es decisión del usuario."""
        rpc = RpcConnection(self._connect.connect(), client_id)
        try:
            reply = rpc.request(
                "AUTHORIZE",
                {"client_id": client_id, "scopes": SCOPES},
                AUTHORIZE_TIMEOUT_SECONDS,
            )
            tokens = self._exchange(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "code": str(reply.get("code", "")),
                    "redirect_uri": REDIRECT_URI,
                }
            )
        finally:
            rpc.close()
        keys = {"client_id": client_id, "client_secret": client_secret}
        self._save_tokens({**self._store.load(), **keys}, tokens)
        self._channels_at = float("-inf")
        return len(self.voice_channels())

    def _session(self) -> RpcConnection:
        secrets = self._store.load()
        if not secrets.get("refresh_token"):
            raise DiscordError("Conecta Discord primero en Configuración.")
        if float(secrets.get("expires_at", 0)) - time.time() < TOKEN_MARGIN_SECONDS:
            tokens = self._exchange(
                {
                    "client_id": str(secrets["client_id"]),
                    "client_secret": str(secrets["client_secret"]),
                    "grant_type": "refresh_token",
                    "refresh_token": str(secrets["refresh_token"]),
                }
            )
            secrets = self._save_tokens(secrets, tokens)
        rpc = RpcConnection(self._connect.connect(), str(secrets["client_id"]))
        try:
            rpc.request("AUTHENTICATE", {"access_token": secrets["access_token"]})
        except DiscordError:
            rpc.close()
            raise
        return rpc

    def voice_channels(self) -> list[VoiceChannel]:
        if time.monotonic() - self._channels_at < CHANNELS_CACHE_SECONDS:
            return self._channels
        rpc = self._session()
        try:
            found = []
            for guild in rpc.request("GET_GUILDS", {}).get("guilds", []):
                reply = rpc.request("GET_CHANNELS", {"guild_id": guild["id"]})
                found.extend(
                    VoiceChannel(str(channel["id"]), str(channel["name"]), str(guild["name"]))
                    for channel in reply.get("channels", [])
                    if channel.get("type") in (CHANNEL_VOICE, CHANNEL_STAGE)
                )
        finally:
            rpc.close()
        self._channels, self._channels_at = found, time.monotonic()
        return found

    def find(self, target: str) -> VoiceChannel:
        channels = self.voice_channels()
        scored = sorted(((_score(c, target), c) for c in channels), key=lambda item: -item[0])
        if not scored or scored[0][0] < MIN_NAME_SIMILARITY:
            raise DiscordError(f"No encuentro el canal de voz {target}.")
        best = [channel for score, channel in scored if score == scored[0][0]]
        guilds = {channel.guild for channel in best}
        if len(best) > 1 and len(guilds) > 1:
            names = ", ".join(sorted(guilds)[:3])
            raise DiscordError(f"Hay varios canales así, en {names}. Dime también el servidor.")
        return best[0]

    def favorite(self) -> VoiceChannel:
        """El último canal al que se entró: "el de siempre"."""
        last = self._store.load().get("last_channel")
        for channel in self.voice_channels():
            if channel.id == last:
                return channel
        raise DiscordError("Aún no sé cuál es tu canal de siempre: dímelo una vez por su nombre.")

    def join(self, channel: VoiceChannel) -> None:
        """Se usa `force` porque el usuario ya aprobó entrar, aunque estuviera en otro canal."""
        rpc = self._session()
        try:
            rpc.request(
                "SELECT_VOICE_CHANNEL",
                {"channel_id": channel.id, "timeout": JOIN_TIMEOUT_SECONDS, "force": True},
                JOIN_TIMEOUT_SECONDS + REPLY_TIMEOUT_SECONDS,
            )
        finally:
            rpc.close()
        self._store.save({**self._store.load(), "last_channel": channel.id})

    def leave(self) -> None:
        rpc = self._session()
        try:
            rpc.request("SELECT_VOICE_CHANNEL", {"channel_id": None})
        finally:
            rpc.close()

    def contacts(self) -> list[Contact]:
        saved = self._saved_contacts()
        return [Contact(name, saved[name]) for name in sorted(saved, key=str.casefold)]

    def add_contact(self, name: str, chat: str) -> Contact:
        """Admite el ID del canal o el enlace al chat. Un nombre repetido se sustituye."""
        chat_id = _CHAT_ID.search(chat)
        if not name.strip() or chat_id is None:
            raise DiscordError("Faltan el nombre o el ID del canal del chat.")
        key = name_key(name)
        kept = {k: v for k, v in self._saved_contacts().items() if name_key(k) != key}
        contact = Contact(name.strip(), chat_id.group())
        self._save_contacts({**kept, contact.name: contact.chat_id})
        return contact

    def remove_contact(self, name: str) -> None:
        self._save_contacts({k: v for k, v in self._saved_contacts().items() if k != name})

    def _saved_contacts(self) -> dict[str, str]:
        return dict(self._store.load().get("contacts", {}))

    def _save_contacts(self, contacts: dict[str, str]) -> None:
        self._store.save({**self._store.load(), "contacts": contacts})

    def find_contact(self, target: str) -> Contact:
        """Por parecido, como los canales: la voz rara vez escribe bien un nombre."""
        key = name_key(target)
        scored = [(name_similarity(key, name_key(c.name)), c) for c in self.contacts()]
        best = max((score for score, _ in scored), default=0.0)
        found = [contact for score, contact in scored if score == best]
        if best < MIN_NAME_SIMILARITY:
            raise DiscordError(f"No tengo a {target} en tus contactos de Discord. Añádelo en Configuración.")
        if len(found) > 1:
            names = ", ".join(contact.name for contact in found[:3])
            raise DiscordError(f"¿A quién te refieres: {names}?")
        return found[0]

    def open_chat(self, contact: Contact) -> None:
        """Solo cambia lo que se ve en Discord. El RPC no tiene orden para enviar mensajes."""
        rpc = self._session()
        try:
            rpc.request(
                "SELECT_TEXT_CHANNEL",
                {"channel_id": contact.chat_id, "timeout": JOIN_TIMEOUT_SECONDS},
                JOIN_TIMEOUT_SECONDS + REPLY_TIMEOUT_SECONDS,
            )
        finally:
            rpc.close()

    def forget(self) -> None:
        self._store.clear()
        self._channels, self._channels_at = [], float("-inf")
